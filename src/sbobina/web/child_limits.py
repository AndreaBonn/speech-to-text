"""Memory limit shared by every untrusted child process (A4, security).

Applied before the child touches the document it was handed: extraction and
OCR both parse attacker-controlled files, and a parser that loops or
allocates without bound must not be able to exhaust the host's memory.
"""

try:
    import resource

    HAS_RESOURCE_LIMIT = True
except ImportError:  # Windows has no RLIMIT_AS; the parent's timeout still applies.
    HAS_RESOURCE_LIMIT = False

__all__ = ["HAS_RESOURCE_LIMIT", "_apply_memory_limit"]


def _apply_memory_limit(max_memory_mb: int) -> None:
    if not HAS_RESOURCE_LIMIT:
        return
    limit_bytes = max_memory_mb * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (limit_bytes, limit_bytes))
