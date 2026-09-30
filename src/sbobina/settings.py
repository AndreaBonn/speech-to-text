from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration; every field can be overridden with ``SBOBINA_<NAME>``."""

    model_config = SettingsConfigDict(
        env_prefix="SBOBINA_", env_file=".env", extra="ignore"
    )

    whisper_model: str = "large-v3"
    device: str = "cuda"
    compute_type: str = "float16"
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
    uncertain_threshold: float = Field(default=0.7, gt=0.0, le=1.0)
    paragraph_gap_s: float = Field(default=2.0, gt=0.0)
    paragraph_max_s: float = Field(default=120.0, gt=0.0)


settings = Settings()
