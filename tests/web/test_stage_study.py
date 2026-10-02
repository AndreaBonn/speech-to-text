from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import JsonValue
from study_fixtures import FakeChat, response_fixture, transcript_fixture

from sbobina.correction import CorrectorUnavailableError
from sbobina.models import save_transcript
from sbobina.settings import settings
from sbobina.study_pipeline import StudyChat
from sbobina.study_render import load_study
from sbobina.web import stage_runner
from sbobina.web.api_files import transcript_revision
from sbobina.web.job_models import JobConfig
from sbobina.web.job_store import JobStore


@pytest.fixture
def study_directory(tmp_path: Path) -> Path:
    store = JobStore(data_dir=tmp_path)
    record = store.create(config=JobConfig(ollama_model="custom-study"))
    directory = store.jobs_dir / str(record.id)
    save_transcript(transcript=transcript_fixture(), path=directory / "audio.json")
    return directory


@pytest.mark.parametrize("corrected", [True, False])
def test_study_stage_writes_pair_revision_and_every_block_progress(
    study_directory: Path, corrected: bool
) -> None:
    source = prepare_source(directory=study_directory, corrected=corrected)
    chat = FakeChat(responses=[response_fixture()])
    store = JobStore(data_dir=study_directory.parent.parent)
    record_before = store.get(job_id=study_directory.name)
    with (
        patch("sbobina.study_command._prepare_chat", return_value=chat) as prepare,
        patch.object(
            JobStore,
            "write_progress",
            autospec=True,
            side_effect=JobStore.write_progress,
        ) as write,
    ):
        result = stage_runner.run_stage(stage="study", job_dir=study_directory)
    assert result == 0
    assert_study_files(directory=study_directory, source=source, corrected=corrected)
    assert [call.kwargs["progress"]["progress"] for call in write.call_args_list] == [
        0.0,
        1.0,
        1.0,
    ]
    assert store.read_progress(job_id=study_directory.name)["stage"] == "study"
    assert store.get(job_id=study_directory.name) == record_before
    prepare.assert_called_once_with(model="custom-study", host=settings.ollama_host)


@pytest.mark.parametrize("when", ["prepare", "chat"])
def test_study_unavailable_keeps_previous_material(
    study_directory: Path, when: str
) -> None:
    for suffix in ("json", "md"):
        (study_directory / f"audio.studio.{suffix}").write_text(f"previous {suffix}")
    failure = CorrectorUnavailableError("offline")
    chat = FakeChat(responses=[failure])
    with patch(
        "sbobina.study_command._prepare_chat",
        side_effect=failure if when == "prepare" else None,
        return_value=chat,
    ):
        result = stage_runner.run_stage(stage="study", job_dir=study_directory)
    assert result == 2
    assert (study_directory / "audio.studio.json").read_text() == "previous json"
    assert (study_directory / "audio.studio.md").read_text() == "previous md"
    assert (
        JobStore(data_dir=study_directory.parent.parent).read_progress(
            job_id=study_directory.name
        )["progress"]
        == 0.0
    )


def test_study_writes_intermediate_progress_without_throttle(
    study_directory: Path,
) -> None:
    store = JobStore(data_dir=study_directory.parent.parent)
    seen: list[JsonValue] = []

    def prepare(model: str, host: str) -> StudyChat:
        def answer(request: object) -> str:
            seen.append(store.read_progress(job_id=study_directory.name)["progress"])
            return response_fixture()

        return answer

    with (
        patch("sbobina.study_command._prepare_chat", side_effect=prepare),
        patch.object(
            stage_runner,
            "settings",
            settings.model_copy(update={"study_block_words": 3}),
        ),
    ):
        result = stage_runner.run_stage(
            stage="study", job_dir=study_directory, now=lambda: 0.0
        )
    assert result == 0
    assert seen == [0.0, 1 / 3, 2 / 3]
    assert store.read_progress(job_id=study_directory.name)["progress"] == 1.0


def test_study_missing_transcript_fails_before_chat(study_directory: Path) -> None:
    (study_directory / "audio.json").unlink()
    with patch("sbobina.study_command._prepare_chat") as prepare:
        assert stage_runner.run_stage(stage="study", job_dir=study_directory) == 1
    prepare.assert_not_called()
    assert (study_directory / "job.json").is_file()


def test_main_accepts_study(study_directory: Path) -> None:
    with (
        patch.object(stage_runner, "start_stdin_watchdog"),
        patch.object(stage_runner, "run_stage", return_value=0) as run,
    ):
        assert stage_runner.main(argv=["study", str(study_directory)]) == 0
    run.assert_called_once_with(stage="study", job_dir=study_directory)


def prepare_source(directory: Path, corrected: bool) -> Path:
    transcript = transcript_fixture()
    source = directory / ("audio.corretto.json" if corrected else "audio.json")
    save_transcript(transcript=transcript, path=source)
    source.write_bytes(source.read_bytes().replace(b"\n", b"\r\n"))
    if corrected:
        save_transcript(
            transcript=replace(transcript, segments=()),
            path=directory / "audio.json",
        )
    return source


def assert_study_files(directory: Path, source: Path, corrected: bool) -> None:
    transcript = transcript_fixture()
    loaded = load_study(path=directory / "audio.studio.json", transcript=transcript)
    assert loaded.result.source_variant == ("corrected" if corrected else "original")
    assert loaded.result.source_revision == transcript_revision(
        source.read_bytes().decode("utf-8")
    )
    assert loaded.result.model == "custom-study"
    assert "§2 00:10" in (directory / "audio.studio.md").read_text()
