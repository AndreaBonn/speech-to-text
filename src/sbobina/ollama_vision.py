"""Boundary for Ollama vision models: read one rendered page image (F5 OCR)."""

import logging
from importlib import resources

import httpx
from ollama import Client, GenerateResponse, ResponseError

from sbobina.correction import CorrectorUnavailableError

logger = logging.getLogger("sbobina")

# ocr-v2 asks for formulas in LaTeX between \( \) and \[ \] (V10, eval-math.md).
PROMPT_FILE = "ocr-v2.md"
PROMPT_VERSION = PROMPT_FILE.removesuffix(".md")
# qwen2.5vl:7b on CPU (T050): ~172s per page at scale 1.0 with this context size.
OCR_CONTEXT_TOKENS = 4096


def _prompt(prompt_file: str) -> str:
    return (
        resources.files("sbobina.prompts")
        .joinpath(prompt_file)
        .read_text(encoding="utf-8")
    )


def _log_usage(response: GenerateResponse) -> None:
    logger.info(
        "Ollama OCR: prompt_tokens=%s output_tokens=%s",
        response.prompt_eval_count,
        response.eval_count,
    )


def read_page_image(
    client: Client, model: str, png: bytes, prompt_file: str = PROMPT_FILE
) -> str:
    """Return the page transcript, or raise if Ollama is unreachable."""
    try:
        response = client.generate(
            model=model,
            prompt=_prompt(prompt_file=prompt_file),
            images=[png],
            options={"temperature": 0, "num_ctx": OCR_CONTEXT_TOKENS},
        )
    except (ConnectionError, ResponseError, httpx.TransportError) as err:
        raise CorrectorUnavailableError(f"{type(err).__name__}: {err}") from err
    _log_usage(response=response)
    return (response.response or "").strip()
