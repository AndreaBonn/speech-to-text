import logging

from sbobina import ollama_embed
from sbobina.ollama_embed import EmbeddingUnavailableError
from sbobina.settings import Settings

logger = logging.getLogger(__name__)


def embedding_unavailable_reason(settings: Settings, timeout_s: float) -> str | None:
    try:
        ollama_embed.model_status(
            host=settings.ollama_host,
            model=settings.embedding_model,
            timeout_s=timeout_s,
        )
    except EmbeddingUnavailableError as error:
        logger.warning("Automatic embedding unavailable: %s", error.reason)
        return error.reason
    return None
