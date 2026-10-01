import logging

import httpx
import ollama

logger = logging.getLogger(__name__)


def unload_ollama_models(host: str) -> None:
    """Release resident Ollama models; log client failures without blocking jobs."""
    try:
        client = ollama.Client(host=host)
        for model in client.ps().models:
            if model.model:
                client.generate(model=model.model, keep_alive=0)
    # ollama maps only refused connections to ConnectionError: a timeout
    # surfaces as httpx.HTTPError and must not fail the transcription either.
    except (ConnectionError, ollama.ResponseError, httpx.HTTPError) as error:
        logger.warning("Could not release Ollama models on %s: %s", host, error)
