import json
from pathlib import Path
from typing import Literal

import pytest
from pydantic import ValidationError

from sbobina.platform_info import RuntimeChoice
from sbobina.settings import Settings
from sbobina.web.job_models import (
    JobConfig,
    JobRecord,
    JobStage,
    JobStatus,
    WorkItem,
)
from sbobina.web.job_store import JobStore


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1"])
def test_settings_accept_loopback(host: str) -> None:
    config = Settings(web_host=host)
    assert config.web_host == host
    assert (config.web_port, config.data_dir, config.web_max_upload_mb) == (
        8765,
        Path("data"),
        1024,
    )


def test_settings_reject_public_bind() -> None:
    with pytest.raises(ValidationError) as caught:
        Settings(web_host="0.0.0.0")
    assert caught.value.errors()[0]["loc"] == ("web_host",)


def test_job_config_reports_each_invalid_field() -> None:
    with pytest.raises(ValidationError) as caught:
        JobConfig(beam_size=0, uncertain_threshold=1.5, whisper_model="xl")
    assert {error["loc"] for error in caught.value.errors()} == {
        ("beam_size",),
        ("uncertain_threshold",),
        ("whisper_model",),
    }


@pytest.mark.parametrize("model", ["auto", "tiny", "large-v3", "turbo"])
def test_job_config_accepts_supported_model(model: str) -> None:
    assert JobConfig(whisper_model=model).whisper_model == model


@pytest.mark.parametrize(
    "overrides",
    [
        {"beam_size": 11},
        {"uncertain_threshold": 0},
        {"ollama_model": "  "},
        {"subject": "x" * 101},
        {"device": "metal"},
        {"compute_type": "float64"},
    ],
)
def test_job_config_rejects_invalid_overrides(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        JobConfig.model_validate(overrides)


def test_job_config_uses_settings_and_runtime_defaults() -> None:
    config = Settings(beam_size=8, vad_filter=True, ollama_model="local:test")
    runtime = RuntimeChoice(
        device="cpu",
        compute_type="int8",
        whisper_model="tiny",
        cpu_threads=4,
        reason="test",
    )
    job = JobConfig.from_settings(config=config, runtime=runtime)
    assert (job.beam_size, job.vad_filter, job.ollama_model) == (8, True, "local:test")
    assert (job.device, job.compute_type, job.whisper_model) == ("cpu", "int8", "tiny")
    assert (
        JobConfig(subject="x" * 100, beam_size=10, uncertain_threshold=1).subject
        == "x" * 100
    )


def test_job_config_without_runtime_keeps_the_settings_choices() -> None:
    config = Settings(device="cpu", compute_type="int8", whisper_model="tiny")

    job = JobConfig.from_settings(config=config)

    assert (job.device, job.compute_type, job.whisper_model) == ("cpu", "int8", "tiny")


def test_record_round_trips_json() -> None:
    from datetime import UTC, datetime
    from uuid import uuid4

    now = datetime.now(tz=UTC)
    record = JobRecord(
        id=uuid4(),
        config=JobConfig(),
        status=JobStatus.QUEUED,
        stage=JobStage.QUEUED,
        created_at=now,
        updated_at=now,
    )
    assert JobRecord.model_validate_json(record.model_dump_json()) == record
    assert record.pid is None


def test_job_record_legacy_json_loads_without_import_fields(tmp_path: Path) -> None:
    raw = {
        "id": "11111111-1111-4111-8111-111111111111",
        "status": "done",
        "stage": "done",
        "config": {},
        "created_at": "2026-10-05T00:00:00Z",
        "updated_at": "2026-10-05T00:00:00Z",
    }
    directory = tmp_path / "jobs" / str(raw["id"])
    directory.mkdir(parents=True)
    (directory / "job.json").write_text(data=json.dumps(obj=raw), encoding="utf-8")

    record = JobStore(data_dir=tmp_path).get(job_id=str(raw["id"]))

    assert record.status == JobStatus.DONE
    assert record.imported is False
    assert record.import_id is None
    imported = JobRecord.model_validate(
        obj=raw | {"imported": True, "import_id": raw["id"]}
    )
    assert imported.imported is True
    assert imported.import_id == raw["id"]
    assert (
        JobRecord.model_validate_json(json_data=imported.model_dump_json()) == imported
    )


@pytest.mark.parametrize(
    ("action", "course_id"),
    [("generation", None), ("ocr", None), ("pipeline", "c1"), ("study", "c1")],
)
def test_work_item_course_id_only_for_course_scoped_actions(
    action: Literal["pipeline", "study", "generation", "ocr"], course_id: str | None
) -> None:
    with pytest.raises(ValidationError, match="course-scoped"):
        WorkItem(job_id="j1", action=action, course_id=course_id)
