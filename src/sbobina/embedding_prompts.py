"""Per-family embedding prompts: Ollama templates add none, so the caller must."""

QWEN3_QUERY_INSTRUCTION = (
    "Instruct: Given a question, retrieve relevant passages that answer it\n"
    "Query:{query}"
)
# EmbeddingGemma model card § Prompt instructions: retrieval query and document.
GEMMA_QUERY_INSTRUCTION = "task: search result | query: {query}"
GEMMA_DOCUMENT_TEMPLATE = "title: none | text: {text}"
QWEN3_FAMILY = "qwen3-embedding"
GEMMA_FAMILY = "embeddinggemma"
BGE_M3_FAMILY = "bge-m3"
KNOWN_FAMILIES = (QWEN3_FAMILY, GEMMA_FAMILY, BGE_M3_FAMILY)


def model_family(model: str) -> str:
    """The prompt family of an Ollama model tag; unknown families are refused.

    Falling back to "no prompt" would silently lower a new model's measured
    recall, so a model joins the harness only by being added here.
    """
    for family in KNOWN_FAMILIES:
        if model.startswith(family):
            return family
    raise ValueError(f"unknown embedding model family for {model!r}")


def apply_query_instruction(*, question: str, enabled: bool, model: str) -> str:
    """Wrap the question in the query prompt its model family was trained with.

    Ollama's templates add none (eval.md § Verifiche su Ollama), so the code
    must. Qwen3-embedding and EmbeddingGemma expect a query prefix; bge-m3
    needs no instruction for retrieval.
    """
    if not enabled:
        return question
    family = model_family(model)
    if family == QWEN3_FAMILY:
        return QWEN3_QUERY_INSTRUCTION.format(query=question)
    if family == GEMMA_FAMILY:
        return GEMMA_QUERY_INSTRUCTION.format(query=question)
    return question


def format_document(*, text: str, model: str) -> str:
    """Document-side prompt: only EmbeddingGemma expects one."""
    if model_family(model) == GEMMA_FAMILY:
        return GEMMA_DOCUMENT_TEMPLATE.format(text=text)
    return text
