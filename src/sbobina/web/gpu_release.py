import logging

import httpx
import ollama

logger = logging.getLogger(__name__)


def unload_ollama_models(host: str) -> None:
    """Release resident Ollama models; log client failures without blocking jobs."""
    try:
        client = ollama.Client(host=host)
        models = client.ps().models
    # ollama maps only refused connections to ConnectionError: a timeout
    # surfaces as httpx.HTTPError and must not fail the transcription either.
    except (ConnectionError, ollama.ResponseError, httpx.HTTPError) as error:
        logger.warning("Could not release Ollama models on %s: %s", host, error)
        return

    for model in models:
        if not model.model:
            continue
        try:
            client.generate(model=model.model, keep_alive=0)
        except (ConnectionError, ollama.ResponseError, httpx.HTTPError) as error:
            logger.warning(
                "Could not release Ollama model %s on %s: %s", model.model, host, error
            )
