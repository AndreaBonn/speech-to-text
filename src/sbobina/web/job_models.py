from datetime import datetime
from enum import StrEnum

from faster_whisper.utils import available_models
from pydantic import UUID4, BaseModel, ConfigDict, Field, JsonValue, field_validator

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
