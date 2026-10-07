from __future__ import annotations

import argparse
import logging
from functools import partial

from ollama import Client

from sbobina.course_registry import find_by_key, iter_courses
from sbobina.ollama_embed import EmbeddingUnavailableError, embed_texts, model_status
from sbobina.settings import settings
from sbobina.web.job_store import JobStore
from sbobina.web.vector_reconcile import (
    CourseEmbedding,
    EmbeddingConfig,
    EmbeddingProgress,
    embed_course,
)
from sbobina.web.vector_store import VectorStore

logger = logging.getLogger("sbobina")
MODEL_MISSING_EXIT = 2
MODEL_CHANGE_EXIT = 3


def add_semantic_parser(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    command = commands.add_parser(
        "indicizza-semantico", help="Indicizza i corsi per la ricerca semantica"
    )
    scope = command.add_mutually_exclusive_group(required=True)
    scope.add_argument("--corso", help="Chiave del corso da indicizzare")
    scope.add_argument("--tutti", action="store_true", help="Indicizza tutti i corsi")
    scope.add_argument(
        "--backfill",
        action="store_true",
        help="Mette in coda i corsi non indicizzati del tutto; partono con sbobina web",
    )
    command.add_argument(
        "--conferma-cambio-modello",
        action="store_true",
        help="Con --backfill, ricostruisce l'indice dopo un cambio di modello",
    )
    command.set_defaults(handler=cmd_indicizza_semantico)


def _course_keys(args: argparse.Namespace) -> list[str]:
    courses_dir = settings.data_dir / "courses"
    if args.tutti:
        return [course.key for course in iter_courses(courses_dir=courses_dir)]
    course = find_by_key(courses_dir=courses_dir, key=args.corso)
    if course is None:
        raise ValueError(f"Corso non trovato: {args.corso}")
    return [course.key]


def _prepare_embedding() -> EmbeddingConfig:
    status = model_status(
        host=settings.ollama_host,
        model=settings.embedding_model,
        timeout_s=settings.embedding_timeout_s,
    )
    client = Client(host=settings.ollama_host)
    model = settings.embedding_model
    return EmbeddingConfig(
        model=model,
        status=status,
        embedder=lambda texts: embed_texts(
            client=client,
            model=model,
            texts=texts,
            mode="document",
        ),
    )


def _print_progress(course_key: str, update: EmbeddingProgress) -> None:
    truncated = (
        "1 passaggio troncato"
        if update.truncated == 1
        else f"{update.truncated} passaggi troncati"
    )
    print(
        f"{course_key}: copertura {update.processed}/{update.total}; "
        f"{truncated}; {update.units_per_second:.2f} unità/s",
        flush=True,
    )


def _index_courses(keys: list[str], embedding: EmbeddingConfig | None) -> None:
    context = CourseEmbedding(
        store=JobStore(data_dir=settings.data_dir),
        vectors=VectorStore(path=settings.data_dir / "vectors.sqlite3"),
        embedding=embedding if embedding is not None else _prepare_embedding(),
    )
    for key in keys:
        embed_course(
            context=context, course_key=key, progress=partial(_print_progress, key)
        )


def cmd_indicizza_semantico(
    args: argparse.Namespace, embedding: EmbeddingConfig | None = None
) -> int:
    """Index selected courses; injected embedding bypasses Ollama preparation."""
    model = embedding.model if embedding is not None else settings.embedding_model
    try:
        if getattr(args, "backfill", False):
            return _queue_backfill(confirm_model_change=args.conferma_cambio_modello)
        keys = _course_keys(args=args)
        if not keys:
            print("Nessun corso da indicizzare.")
            return 0
        _index_courses(keys=keys, embedding=embedding)
    except EmbeddingUnavailableError as error:
        if error.reason == "model_missing":
            logger.exception("Modello assente. Esegui: ollama pull %s", model)
            return MODEL_MISSING_EXIT
        logger.exception("Embedding non disponibile: %s", error.reason)
        return 1
    except (OSError, ValueError) as error:
        detail = str(error)
        logger.exception("Indicizzazione non riuscita: %s", detail)
        return 1
    return 0


def _queue_backfill(*, confirm_model_change: bool) -> int:
    # Lazy: the queue modules pull in the web layer, which other commands skip.
    from sbobina.web.embedding_backfill import enqueue_backfill

    status = model_status(
        host=settings.ollama_host,
        model=settings.embedding_model,
        timeout_s=settings.embedding_timeout_s,
    )
    vectors = VectorStore(path=settings.data_dir / "vectors.sqlite3")
    try:
        result = enqueue_backfill(
            store=JobStore(data_dir=settings.data_dir),
            vectors=vectors,
            status=status,
            confirm_model_change=confirm_model_change,
        )
    finally:
        vectors.close()
    if result.model_change_pending:
        logger.error(
            "Il modello di embedding è cambiato e l'indice va ricostruito: "
            "rilancia con --conferma-cambio-modello"
        )
        return MODEL_CHANGE_EXIT
    count = len(result.items)
    noun = "corso" if count == 1 else "corsi"
    print(
        f"{count} {noun} in coda: l'indicizzazione parte all'avvio di sbobina web "
        "(se è già aperto, riavvialo)."
    )
    return 0
