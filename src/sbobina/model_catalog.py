import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from pydantic import JsonValue

Level = Literal["bassa", "media", "alta"]

AUTO_VALUE = "auto"
OTHER_OLLAMA_VALUE = "__altro__"
OTHER_OLLAMA_LABEL = "Altro modello…"
ENGLISH_ONLY_NOTE = "Solo inglese: non adatto alle lezioni in italiano."
UNKNOWN_NOTE = "Nessuna descrizione disponibile per questo modello."
DEFAULT_OLLAMA_MEASURED = (
    "Misurato: lezione di 85 min corretta in circa 18 min su RTX 4060."
)
OTHER_OLLAMA_NOTE = (
    "Scrivi il nome di un modello Ollama, per esempio qwen3.5:4b: "
    "se non è installato viene scaricato all'avvio della correzione."
)
_BILLION_PARAMS = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*B\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class ModelProfile:
    """What a non-technical user needs to pick a model: quality, speed, when."""

    precision: Level | None
    speed: Level | None
    note: str
    measured: str | None = None
    download_size: str | None = None


@dataclass(frozen=True)
class ModelOption:
    value: str
    label: str
    lines: tuple[str, ...]


# Relative speed from the OpenAI Whisper model table
# (https://github.com/openai/whisper#available-models-and-languages), quality
# ordered by model size as in that table; download sizes are
# the Hugging Face repositories on 2026-10-01; "measured" lines come from runs
# on this project's hardware recorded in docs/REPORT_ATTIVITA.md.
WHISPER_PROFILES: Mapping[str, ModelProfile] = {
    "tiny": ModelProfile(
        precision="bassa",
        speed="alta",
        note="Solo per prove rapide: molti errori sull'italiano.",
        download_size="80 MB",
    ),
    "base": ModelProfile(
        precision="bassa",
        speed="alta",
        note="Leggero, ma sbaglia spesso le parole tecniche.",
        download_size="150 MB",
    ),
    "small": ModelProfile(
        precision="media",
        speed="alta",
        note="Compromesso per computer poco potenti.",
        download_size="490 MB",
    ),
    "medium": ModelProfile(
        precision="media",
        speed="media",
        note="Più preciso di small, circa il doppio più lento.",
        download_size="1,5 GB",
    ),
    "large-v1": ModelProfile(
        precision="alta",
        speed="bassa",
        note="Prima versione di large: preferisci large-v3.",
        download_size="3,1 GB",
    ),
    "large-v2": ModelProfile(
        precision="alta",
        speed="bassa",
        note="Versione precedente di large-v3.",
        download_size="3,1 GB",
    ),
    "large-v3": ModelProfile(
        precision="alta",
        speed="bassa",
        note="Il più preciso. Consigliato con scheda NVIDIA.",
        measured="Misurato: lezione di 85 min trascritta in circa 6,5 min su RTX 4060.",
        download_size="3,1 GB",
    ),
    "large-v3-turbo": ModelProfile(
        precision="alta",
        speed="alta",
        note="Quasi preciso come large-v3 e molto più veloce. "
        "Consigliato senza scheda NVIDIA.",
        measured=(
            "Misurato: lezione di 90 min trascritta in circa mezz'ora "
            "su processore Intel i7 di 13ª generazione."
        ),
        download_size="1,6 GB",
    ),
}
_ENGLISH_ONLY_SIZES: Mapping[str, str] = {
    "distil-large-v2": "1,5 GB",
    "distil-large-v3": "1,5 GB",
    "distil-large-v3.5": "1,5 GB",
}


def whisper_profile(name: str) -> ModelProfile:
    """Profile of a Whisper model by its canonical faster-whisper name."""
    if name in WHISPER_PROFILES:
        return WHISPER_PROFILES[name]
    if name.endswith(".en") or name in _ENGLISH_ONLY_SIZES:
        return ModelProfile(
            precision=None,
            speed=None,
            note=ENGLISH_ONLY_NOTE,
            download_size=_ENGLISH_ONLY_SIZES.get(name),
        )
    return ModelProfile(precision=None, speed=None, note=UNKNOWN_NOTE)


def parse_billion_params(parameter_size: str | None) -> float | None:
    """``"9.7B"`` -> ``9.7``; None when Ollama reports another unit or nothing."""
    match = _BILLION_PARAMS.match(parameter_size or "")
    return float(match.group(1)) if match else None


def ollama_profile(billions: float | None) -> ModelProfile:
    """Estimate quality and speed of a correction model from its parameter count.

    Larger models follow the correction rules better but answer more slowly;
    the bands are a rule of thumb, not a measurement, and the note says so.
    """
    if billions is None:
        return ModelProfile(precision=None, speed=None, note=UNKNOWN_NOTE)
    size = f"{billions:g}".replace(".", ",")
    estimate = f"Stima in base ai {size} miliardi di parametri."
    if billions < 3:
        return ModelProfile(
            precision="bassa", speed="alta", note=f"Veloce, corregge poco. {estimate}"
        )
    if billions < 7:
        return ModelProfile(
            precision="media", speed="alta", note=f"Equilibrato. {estimate}"
        )
    if billions < 14:
        return ModelProfile(
            precision="alta", speed="media", note=f"Corregge bene. {estimate}"
        )
    return ModelProfile(
        precision="alta",
        speed="bassa",
        note=f"Molto lento, può non stare nella memoria della scheda video. {estimate}",
    )


def describe(profile: ModelProfile) -> tuple[str, ...]:
    """Lines shown under the select for the chosen model."""
    lines: list[str] = []
    if profile.precision is not None and profile.speed is not None:
        lines.append(f"Precisione: {profile.precision} · Velocità: {profile.speed}")
    lines.append(profile.note)
    if profile.measured is not None:
        lines.append(profile.measured)
    return tuple(lines)


def whisper_options(
    models: Sequence[Mapping[str, JsonValue]], gpu_model: str, cpu_model: str
) -> list[ModelOption]:
    """Select options for the Whisper models listed by ``list_whisper_models``."""
    options = [
        ModelOption(
            value=AUTO_VALUE,
            label="Automatico",
            lines=(f"Usa {gpu_model} con scheda NVIDIA e {cpu_model} sul processore.",),
        )
    ]
    for model in models:
        name = str(model["name"])
        profile = whisper_profile(name=name)
        if model["downloaded"]:
            state = "scaricato"
        elif profile.download_size is not None:
            state = f"da scaricare, {profile.download_size}"
        else:
            state = "da scaricare"
        label = f"{name} · {state}"
        if model["recommended_gpu"] or model["recommended_cpu"]:
            label += " · consigliato"
        options.append(ModelOption(value=name, label=label, lines=describe(profile)))
    return options


def ollama_options(
    installed: Sequence[Mapping[str, JsonValue]], default_model: str, is_ready: bool
) -> list[ModelOption]:
    """Installed Ollama models, the default one and a free-text entry.

    When Ollama is not reachable the installed list is unknown, so the default
    model is offered without claiming whether it is installed.
    """
    options: list[ModelOption] = []
    names = [str(model["model"]) for model in installed]
    if default_model not in names:
        state = " · da scaricare all'avvio" if is_ready else ""
        options.append(
            ModelOption(
                value=default_model,
                label=f"{default_model}{state}",
                lines=("Modello predefinito di sbobina.", DEFAULT_OLLAMA_MEASURED),
            )
        )
    for model in installed:
        name = str(model["model"])
        profile = ollama_profile(
            billions=parse_billion_params(_optional_str(model.get("parameter_size")))
        )
        lines = describe(profile)
        if name == default_model:
            lines += (DEFAULT_OLLAMA_MEASURED,)
        options.append(
            ModelOption(value=name, label=f"{name} · installato", lines=lines)
        )
    options.append(
        ModelOption(
            value=OTHER_OLLAMA_VALUE,
            label=OTHER_OLLAMA_LABEL,
            lines=(OTHER_OLLAMA_NOTE,),
        )
    )
    return options


def _optional_str(value: JsonValue) -> str | None:
    return value if isinstance(value, str) else None
