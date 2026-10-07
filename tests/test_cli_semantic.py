import logging
from argparse import Namespace
from pathlib import Path

import pytest
from vector_reconcile_fixtures import (
    FakeEmbedder,
    make_context,
    write_course,
    write_pages,
)

from sbobina import cli, cli_semantic
from sbobina.ollama_embed import EmbeddingUnavailableError, ModelStatus
from sbobina.settings import Settings
from sbobina.web.embedding_store import EmbeddingStatus, load_embed
from sbobina.web.vector_reconcile import embed_course


def test_command_prints_full_coverage_and_truncated_passage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeEmbedder(truncated_text="Passaggio 119")
    context = make_context(tmp_path=tmp_path, fake=fake)
    course = write_course(store=context.store)
    write_pages(
        store=context.store, course=course, texts=[f"Passaggio {i}" for i in range(120)]
    )
    monkeypatch.setattr(cli_semantic, "settings", Settings(data_dir=tmp_path))

    code = cli_semantic.cmd_indicizza_semantico(
        args=Namespace(corso=course.key, tutti=False), embedding=context.embedding
    )

    assert code == 0
    output = capsys.readouterr().out
    assert "copertura 120/120" in output
    assert "1 passaggio troncato" in output
    assert "unità/s" in output


@pytest.mark.parametrize("stage", ["status", "embedding"])
def test_command_missing_model_returns_two_with_pull_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    stage: str,
) -> None:
    context = make_context(tmp_path=tmp_path, fake=FakeEmbedder())
    course = write_course(store=context.store)
    write_pages(store=context.store, course=course, texts=["Testo"])
    monkeypatch.setattr(cli_semantic, "settings", Settings(data_dir=tmp_path))

    def unavailable(**kwargs: object) -> None:
        raise EmbeddingUnavailableError(reason="model_missing")

    monkeypatch.setattr(
        cli_semantic,
        "model_status" if stage == "status" else "embed_texts",
        unavailable,
    )
    if stage == "embedding":
        monkeypatch.setattr(
            cli_semantic, "model_status", lambda **kwargs: context.embedding.status
        )
    with caplog.at_level(logging.ERROR):
        code = cli.main(argv=["indicizza-semantico", "--corso", course.key])

    assert code == 2
    assert "ollama pull qwen3-embedding:8b" in caplog.text
    assert caplog.records[-1].exc_info is not None


@pytest.mark.parametrize(
    "failure",
    [EmbeddingUnavailableError(reason="bad_response"), OSError("disk failure")],
)
def test_cmd_indicizza_semantico_failure_logs_traceback(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    failure: Exception,
) -> None:
    def fail(**kwargs: object) -> None:
        raise failure

    monkeypatch.setattr(cli_semantic, "_course_keys", fail)

    with caplog.at_level(logging.ERROR):
        code = cli_semantic.cmd_indicizza_semantico(args=Namespace(tutti=True))

    assert code == 1
    record = caplog.records[-1]
    assert str(failure) in record.getMessage()
    assert record.exc_info is not None
    assert record.exc_info[1] is failure


def test_command_all_courses_reuses_one_vector_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeEmbedder()
    context = make_context(tmp_path=tmp_path, fake=fake)
    for label in ("Diritto", "Storia"):
        course = write_course(store=context.store, label=label)
        write_pages(store=context.store, course=course, texts=[label])
    monkeypatch.setattr(cli_semantic, "settings", Settings(data_dir=tmp_path))
    constructed: list[Path] = []

    def vectors(path: Path) -> object:
        constructed.append(path)
        return context.vectors

    monkeypatch.setattr(cli_semantic, "VectorStore", vectors)
    code = cli_semantic.cmd_indicizza_semantico(
        args=Namespace(corso=None, tutti=True), embedding=context.embedding
    )

    assert code == 0
    assert len(constructed) == 1
    assert {item.text for call in fake.calls for item in call} == {"Diritto", "Storia"}
    output = capsys.readouterr().out
    assert "diritto: copertura 1/1" in output
    assert "storia: copertura 1/1" in output


def test_command_unknown_course_fails_before_model_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(cli_semantic, "settings", Settings(data_dir=tmp_path))

    code = cli.main(argv=["indicizza-semantico", "--corso", "inesistente"])

    assert code != 0
    assert "Corso non trovato: inesistente" in caplog.text
    assert caplog.records[-1].exc_info is not None


@pytest.mark.parametrize("flags", [[], ["--tutti", "--corso", "diritto"]])
def test_parser_requires_exactly_one_scope(flags: list[str]) -> None:
    with pytest.raises(SystemExit) as error:
        cli.build_parser().parse_args(["indicizza-semantico", *flags])
    assert error.value.code == 2


def test_parser_registers_semantic_command() -> None:
    args = cli.build_parser().parse_args(["indicizza-semantico", "--tutti"])
    assert args.handler is cli_semantic.cmd_indicizza_semantico
    assert args.tutti is True
    assert args.corso is None


def _two_courses_one_indexed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path]:
    context = make_context(tmp_path=tmp_path, fake=FakeEmbedder())
    indexed = write_course(store=context.store, label="Diritto")
    pending = write_course(store=context.store, label="Storia")
    write_pages(store=context.store, course=indexed, texts=["Contratto"])
    write_pages(store=context.store, course=pending, texts=["Impero"])
    embed_course(context=context, course_key=indexed.key, progress=lambda _: None)
    context.vectors.close()
    monkeypatch.setattr(cli_semantic, "settings", Settings(data_dir=tmp_path))
    monkeypatch.setattr(
        cli_semantic, "model_status", lambda **kwargs: context.embedding.status
    )
    courses = context.store.courses_dir
    return courses / indexed.id, courses / pending.id


def test_backfill_queues_only_incomplete_courses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    indexed, pending = _two_courses_one_indexed(
        tmp_path=tmp_path, monkeypatch=monkeypatch
    )

    code = cli.main(argv=["indicizza-semantico", "--backfill"])

    assert code == 0
    queued = load_embed(course_dir=pending)
    assert queued is not None and queued.status is EmbeddingStatus.QUEUED
    assert load_embed(course_dir=indexed) is None
    assert "1 corso in coda" in capsys.readouterr().out


def test_backfill_model_change_requires_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _, pending = _two_courses_one_indexed(tmp_path=tmp_path, monkeypatch=monkeypatch)
    other = ModelStatus(digest="other-digest", dimensions=2)
    monkeypatch.setattr(cli_semantic, "model_status", lambda **kwargs: other)

    blocked = cli.main(argv=["indicizza-semantico", "--backfill"])

    assert blocked == cli_semantic.MODEL_CHANGE_EXIT
    assert "--conferma-cambio-modello" in caplog.text
    assert load_embed(course_dir=pending) is None
    confirmed = cli.main(
        argv=["indicizza-semantico", "--backfill", "--conferma-cambio-modello"]
    )
    assert confirmed == 0
    queued = load_embed(course_dir=pending)
    assert queued is not None and queued.status is EmbeddingStatus.QUEUED
