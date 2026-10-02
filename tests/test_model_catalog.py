import pytest
from pydantic import JsonValue

from sbobina.model_catalog import (
    AUTO_VALUE,
    DEFAULT_OLLAMA_MEASURED,
    ENGLISH_ONLY_NOTE,
    OTHER_OLLAMA_VALUE,
    UNKNOWN_NOTE,
    ModelOption,
    ollama_options,
    ollama_profile,
    parse_billion_params,
    whisper_options,
    whisper_profile,
)


def _whisper(
    name: str, downloaded: bool, gpu: bool = False, cpu: bool = False
) -> dict[str, JsonValue]:
    return {
        "name": name,
        "downloaded": downloaded,
        "recommended_gpu": gpu,
        "recommended_cpu": cpu,
    }


def test_whisper_options_start_with_auto_naming_both_defaults() -> None:
    options = whisper_options(models=[], gpu_model="large-v3", cpu_model="turbo")

    assert options == [
        ModelOption(
            value=AUTO_VALUE,
            label="Automatico",
            lines=("Usa large-v3 con scheda NVIDIA e turbo sul processore.",),
        )
    ]


def test_whisper_options_show_download_state_size_and_recommendation() -> None:
    options = whisper_options(
        models=[
            _whisper(name="large-v3", downloaded=True, gpu=True),
            _whisper(name="medium", downloaded=False),
        ],
        gpu_model="large-v3",
        cpu_model="large-v3-turbo",
    )

    assert [option.label for option in options[1:]] == [
        "large-v3 · scaricato · consigliato",
        "medium · da scaricare, 1,5 GB",
    ]
    assert options[1].lines == (
        "Precisione: alta · Velocità: bassa",
        "Il più preciso. Consigliato con scheda NVIDIA.",
        "Misurato: lezione di 85 min trascritta in circa 6,5 min su RTX 4060.",
    )
    assert options[2].lines == (
        "Precisione: media · Velocità: media",
        "Più preciso di small, circa il doppio più lento.",
    )


@pytest.mark.parametrize("name", ["small.en", "distil-large-v3"])
def test_whisper_profile_english_only_models_have_no_levels(name: str) -> None:
    profile = whisper_profile(name=name)

    assert (profile.precision, profile.speed) == (None, None)
    assert profile.note == ENGLISH_ONLY_NOTE


def test_whisper_profile_unknown_model_says_so() -> None:
    assert whisper_profile(name="large-v9").note == UNKNOWN_NOTE
    assert whisper_profile(name="large-v3").note != UNKNOWN_NOTE


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("9.7B", 9.7),
        ("4B", 4.0),
        (" 27b ", 27.0),
        ("567M", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_billion_params(raw: str | None, expected: float | None) -> None:
    assert parse_billion_params(parameter_size=raw) == expected


@pytest.mark.parametrize(
    ("billions", "precision", "speed"),
    [
        (2.0, "bassa", "alta"),
        (3.0, "media", "alta"),
        (6.9, "media", "alta"),
        (7.0, "alta", "media"),
        (9.7, "alta", "media"),
        (14.0, "alta", "bassa"),
    ],
)
def test_ollama_profile_bands_by_parameter_count(
    billions: float, precision: str, speed: str
) -> None:
    profile = ollama_profile(billions=billions)

    assert (profile.precision, profile.speed) == (precision, speed)
    assert "miliardi di parametri" in profile.note


def test_ollama_profile_without_size_has_no_levels() -> None:
    profile = ollama_profile(billions=None)

    assert (profile.precision, profile.speed, profile.note) == (
        None,
        None,
        UNKNOWN_NOTE,
    )


def test_ollama_options_installed_default_carries_measurement() -> None:
    options = ollama_options(
        installed=[
            {"model": "qwen3.5:9b", "size": 1, "parameter_size": "9.7B"},
            {"model": "qwen3.5:2b", "size": 1, "parameter_size": "2B"},
        ],
        default_model="qwen3.5:9b",
        is_ready=True,
    )

    assert [option.value for option in options] == [
        "qwen3.5:9b",
        "qwen3.5:2b",
        OTHER_OLLAMA_VALUE,
    ]
    assert options[0].label == "qwen3.5:9b · installato"
    assert options[0].lines[-1] == DEFAULT_OLLAMA_MEASURED
    assert DEFAULT_OLLAMA_MEASURED not in options[1].lines
    assert options[1].lines[0] == "Precisione: bassa · Velocità: alta"


def test_ollama_options_missing_default_is_offered_for_download() -> None:
    options = ollama_options(
        installed=[{"model": "llama3:8b", "size": 1, "parameter_size": "8B"}],
        default_model="qwen3.5:9b",
        is_ready=True,
    )

    assert [option.label for option in options] == [
        "qwen3.5:9b · da scaricare all'avvio",
        "llama3:8b · installato",
        "Altro modello…",
    ]


def test_ollama_options_when_ollama_is_down_make_no_install_claim() -> None:
    options = ollama_options(installed=[], default_model="qwen3.5:9b", is_ready=False)

    assert [option.label for option in options] == ["qwen3.5:9b", "Altro modello…"]


def test_whisper_options_unknown_model_without_size_shows_only_its_note() -> None:
    options = whisper_options(
        models=[_whisper(name="large-v9", downloaded=False)],
        gpu_model="large-v3",
        cpu_model="large-v3-turbo",
    )

    assert options[1].label == "large-v9 · da scaricare"
    assert options[1].lines == (UNKNOWN_NOTE,)


def test_whisper_options_marks_the_cpu_recommendation_too() -> None:
    options = whisper_options(
        models=[_whisper(name="large-v3-turbo", downloaded=True, cpu=True)],
        gpu_model="large-v3",
        cpu_model="large-v3-turbo",
    )

    assert options[1].label == "large-v3-turbo · scaricato · consigliato"
