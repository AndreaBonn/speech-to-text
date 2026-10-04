from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Device = Literal["auto", "cuda", "cpu"]
LOOPBACK_HOSTS = ("127.0.0.1", "::1", "localhost")

# CTranslate2 quantization types: https://opennmt.net/CTranslate2/quantization.html
ComputeType = Literal[
    "auto",
    "float32",
    "float16",
    "bfloat16",
    "int16",
    "int8",
    "int8_float32",
    "int8_float16",
    "int8_bfloat16",
]


class Settings(BaseSettings):
    """Runtime configuration; every field can be overridden with ``SBOBINA_<NAME>``."""

    model_config = SettingsConfigDict(
        env_prefix="SBOBINA_", env_file=".env", extra="ignore"
    )

    # "auto" picks whisper_model_gpu on CUDA and whisper_model_cpu on CPU.
    whisper_model: str = "auto"
    whisper_model_gpu: str = "large-v3"
    whisper_model_cpu: str = "large-v3-turbo"
    device: Device = "auto"
    compute_type: ComputeType = "auto"
    cpu_threads: int = Field(default=0, ge=0)
    language: str = "it"
    beam_size: int = Field(default=5, ge=1)
    # Off by default: on hour-long audio, conditioning on previous text is the
    # usual trigger of Whisper's repetition loops. To be re-measured on a gold set.
    condition_on_previous_text: bool = False
    # Off: on an 85-min phone recording Silero VAD merged speech into windows of
    # up to 297 s that Whisper under-decoded (5971 words vs 9136 without VAD).
    vad_filter: bool = False
    ollama_model: str = "qwen3.5:9b"
    ollama_host: str = "http://localhost:11434"
    correction_chunk_words: int = Field(default=200, ge=20)
    study_block_words: int = Field(default=1200, gt=0)
    study_num_predict: int = Field(default=2048, gt=0)
    review_new_per_day: int = Field(default=20, ge=0)
    practice_grading_mode: Literal["auto", "judge", "self"] = "auto"
    uncertain_threshold: float = Field(default=0.7, gt=0.0, le=1.0)
    paragraph_gap_s: float = Field(default=2.0, gt=0.0)
    paragraph_max_s: float = Field(default=120.0, gt=0.0)
    web_host: str = "127.0.0.1"
    web_port: int = 8765
    data_dir: Path = Path("data")
    web_max_upload_mb: int = 1024
    extraction_timeout_s: float = Field(default=120.0, gt=0.0)
    extraction_max_memory_mb: int = Field(default=2048, gt=0)
    course_doc_max_mb: int = Field(default=200, gt=0)
    chat_timeout_s: float = Field(default=120.0, gt=0.0)
    ocr_model: str = "qwen2.5vl:7b"
    # Measured on CPU (eval.md § T050): ~172s/page at scale 1.0, >600s at 2.0.
    ocr_scale: float = Field(default=1.0, gt=0.0)
    # One page took ~172 s on CPU (eval.md T050); a hung Ollama must not hold
    # the single queue worker forever.
    ocr_timeout_s: float = Field(default=900.0, gt=0.0)
    # A4 (security): the supervisor's only worker thread must not block
    # forever behind a hung or looping OCR child.
    ocr_process_timeout_s: float = Field(default=3600.0, gt=0.0)

    @field_validator("web_host")
    @classmethod
    def validate_web_host(cls, value: str) -> str:
        if value not in LOOPBACK_HOSTS:
            raise ValueError("L'host web deve essere 127.0.0.1, ::1 o localhost")
        return value


settings = Settings()
