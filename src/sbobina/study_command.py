import argparse
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ollama import Client
from pydantic import TypeAdapter

from sbobina import llm_corrector, ollama_chat
from sbobina.correction import CorrectorUnavailableError
from sbobina.models import Transcript
from sbobina.render import RenderOptions
from sbobina.settings import settings
from sbobina.study_pipeline import (
    StudyChat,
    StudyOptions,
    generate_study,
    source_revision,
)
from sbobina.study_render import save_study

logger = logging.getLogger("sbobina")
TRANSCRIPT_ADAPTER = TypeAdapter(Transcript)


@dataclass(frozen=True)
class StudyPaths:
    source: Path
    output: Path
    variant: Literal["original", "corrected"]


def select_study_paths(path: Path) -> StudyPaths:
    stem = path.stem.removesuffix(".corretto")
    corrected = path.with_name(f"{stem}.corretto.json")
    source = corrected if corrected.is_file() else path
    return StudyPaths(
        source=source,
        output=path.with_name(f"{stem}.studio.json"),
        variant="corrected" if source == corrected else "original",
    )


def _prepare_chat(model: str, host: str) -> StudyChat:
    llm_corrector.ensure_model(model=model, host=host)
    client = Client(host=host)

    def chat(request: ollama_chat.ChatRequest) -> str:
        return ollama_chat.chat_json(client=client, request=request)

    return chat


def _log_study_progress(done: int, total: int) -> None:
    logger.info("Elaborati %d blocchi di studio su %d", done, total)


def _study_options(model: str, paths: StudyPaths, content: str) -> StudyOptions:
    return StudyOptions(
        model=model,
        block_words=settings.study_block_words,
        num_predict=settings.study_num_predict,
        source_variant=paths.variant,
        source_revision=source_revision(content=content),
    )


def _generate_files(paths: StudyPaths, model: str, chat: StudyChat | None) -> None:
    content = paths.source.read_text(encoding="utf-8")
    transcript = TRANSCRIPT_ADAPTER.validate_json(content)
    result = generate_study(
        transcript=transcript,
        chat=chat
        if chat is not None
        else _prepare_chat(model=model, host=settings.ollama_host),
        options=_study_options(model=model, paths=paths, content=content),
        on_progress=_log_study_progress,
    )
    render_options = RenderOptions(
        uncertain_threshold=settings.uncertain_threshold,
        paragraph_gap_s=settings.paragraph_gap_s,
        paragraph_max_s=settings.paragraph_max_s,
    )
    save_study(
        result=result,
        json_path=paths.output,
        transcript=transcript,
        options=render_options,
    )


def cmd_studio(args: argparse.Namespace, chat: StudyChat | None = None) -> int:
    """Run study generation; an injected chat owns its own model preparation."""
    paths = select_study_paths(path=args.trascrizione)
    model = args.model or settings.ollama_model
    try:
        _generate_files(paths=paths, model=model, chat=chat)
    except (CorrectorUnavailableError, llm_corrector.ModelDownloadError) as err:
        logger.error("Ollama non disponibile per il modello %s: %s", model, err)
        return 1
    except (OSError, ValueError) as err:
        logger.error("Generazione dei materiali di studio non riuscita: %s", err)
        return 1
    logger.info("Scritti %s e %s", paths.output, paths.output.with_suffix(".md"))
    return 0
