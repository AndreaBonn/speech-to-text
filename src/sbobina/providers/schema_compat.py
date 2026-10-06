"""Turn a pydantic JSON schema into the subset cloud providers accept.

Every provider adapter needs a schema with no `$ref`/`$defs` (inlined) and
`additionalProperties: false` on each object, and most reject a handful of
JSON Schema keywords pydantic emits by default (`title`, `minLength`, ...).
Pydantic still validates the response on the caller's side with the
original, stricter model: the keywords this module drops are enforced
there, not lost.
"""

from copy import deepcopy
from typing import Any, cast

_UNSUPPORTED_KEYWORDS = frozenset(
    {
        "title",
        "default",
        "examples",
        "minLength",
        "maxLength",
        "pattern",
        "format",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "minItems",
        "maxItems",
        "uniqueItems",
    }
)


def _resolve_ref(ref: str, defs: dict[str, Any]) -> dict[str, Any]:
    name = ref.removeprefix("#/$defs/")
    return cast(dict[str, Any], defs[name])


def _strip_node(node: Any, defs: dict[str, Any]) -> Any:
    if isinstance(node, list):
        return [_strip_node(node=item, defs=defs) for item in node]
    if not isinstance(node, dict):
        return node
    if "$ref" in node:
        return _strip_node(node=_resolve_ref(ref=node["$ref"], defs=defs), defs=defs)
    cleaned = {
        key: _strip_node(node=value, defs=defs)
        for key, value in node.items()
        if key not in _UNSUPPORTED_KEYWORDS and key != "$defs"
    }
    if cleaned.get("type") == "object":
        cleaned["additionalProperties"] = False
    return cleaned


def portable_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Return a provider-safe copy of ``schema``; never mutates the input.

    Parameters
    ----------
    schema : dict[str, Any]
        A JSON schema as produced by ``BaseModel.model_json_schema()``,
        possibly with ``$defs``/``$ref``.

    Returns
    -------
    dict[str, Any]
        The schema with every ``$ref`` inlined from ``$defs``, the
        unsupported keywords removed, and ``additionalProperties: false``
        added to every object (including nested and inlined ones).
    """
    defs = deepcopy(schema.get("$defs", {}))
    return cast(dict[str, Any], _strip_node(node=schema, defs=defs))
