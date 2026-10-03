from datetime import datetime
from enum import StrEnum
from typing import Literal

from faster_whisper.utils import available_models
from pydantic import (
    UUID4,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

from sbobina.courses import normalize_course_label
from sbobina.platform_info import RuntimeChoice
from sbobina.settings import ComputeType, Device, Settings, settings


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class JobStage(StrEnum):
    QUEUED = "queued"
    TRANSCRIBING = "transcribing"
    CORRECTING = "correcting"
    DONE = "done"
    STUDY = "study"


class WorkItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    job_id: str
    action: Literal["pipeline", "study", "generation"]
    # Set only for "generation": a generation lives under courses/<course_id>,
    # not under a job directory, so the course id travels with the item.
    course_id: str | None = None

    @model_validator(mode="after")
    def _validate_course_id(self) -> "WorkItem":
        if (self.action == "generation") != (self.course_id is not None):
            raise ValueError("course_id is set only for the generation action")
        return self


class StudyStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class StudyRun(BaseModel):
    model_config = ConfigDict(frozen=True, revalidate_instances="always")

    status: StudyStatus
    error: dict[str, JsonValue] | None = None
    updated_at: datetime


class JobConfig(BaseModel):
    model_config = ConfigDict(validate_default=True)

    whisper_model: str = Field(default_factory=lambda: settings.whisper_model)
    device: Device = Field(default_factory=lambda: settings.device)
    compute_type: ComputeType = Field(default_factory=lambda: settings.compute_type)
    beam_size: int = Field(default_factory=lambda: settings.beam_size, ge=1, le=10)
    vad_filter: bool = Field(default_factory=lambda: settings.vad_filter)
    condition_on_previous_text: bool = Field(
        default_factory=lambda: settings.condition_on_previous_text
    )
    uncertain_threshold: float = Field(
        default_factory=lambda: settings.uncertain_threshold, gt=0, le=1
    )
    correct: bool = False
    ollama_model: str = Field(default_factory=lambda: settings.ollama_model)
    subject: str | None = Field(default=None, max_length=100)

    @field_validator("whisper_model")
    @classmethod
    def validate_whisper_model(cls, value: str) -> str:
        if value != "auto" and value not in available_models():
            raise ValueError("Modello Whisper non disponibile")
        return value

    @field_validator("ollama_model")
    @classmethod
    def validate_ollama_model(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Il modello Ollama non può essere vuoto")
        return value

    @classmethod
    def from_settings(
        cls, config: Settings, runtime: RuntimeChoice | None = None
    ) -> "JobConfig":
        values = config.model_dump(include=set(cls.model_fields))
        if runtime is not None:
            values.update(
                device=runtime.device,
                compute_type=runtime.compute_type,
                whisper_model=runtime.whisper_model,
            )
        return cls.model_validate(values)


class LectureMeta(BaseModel):
    model_config = ConfigDict(frozen=True, revalidate_instances="always")

    course: str | None

    @field_validator("course")
    @classmethod
    def validate_course(cls, value: str | None) -> str | None:
        return normalize_course_label(raw=value)


class JobRecord(BaseModel):
    model_config = ConfigDict(frozen=True, revalidate_instances="always")

    id: UUID4
    status: JobStatus
    stage: JobStage
    config: JobConfig
    created_at: datetime
    updated_at: datetime
    pid: int | None = None
    error: dict[str, JsonValue] | None = None
    study: StudyRun | None = None
    # Name of the uploaded file as the user knows it; empty for older jobs.
    source_name: str = ""
