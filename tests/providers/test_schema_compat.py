"""Contract tests: every real ChatRequest.schema must survive portable_schema."""

from typing import Any

import pytest
from pydantic import BaseModel

from sbobina.generation_models import MultipleChoiceResponse, SummaryResponse
from sbobina.grading_models import ProposedJudgement
from sbobina.llm_corrector import _CorrectionResponse
from sbobina.providers.schema_compat import portable_schema
from sbobina.study_models import StudyResponse

REAL_SCHEMAS: list[type[BaseModel]] = [
    _CorrectionResponse,
    StudyResponse,
    ProposedJudgement,
    MultipleChoiceResponse,
    SummaryResponse,
]


def _walk_objects(node: Any) -> list[dict[str, Any]]:
    """Every dict in the tree whose "type" is "object"."""
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        if node.get("type") == "object":
            found.append(node)
        for value in node.values():
            found.extend(_walk_objects(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(_walk_objects(item))
    return found


def _has_ref(node: Any) -> bool:
    if isinstance(node, dict):
        if "$ref" in node:
            return True
        return any(_has_ref(value) for value in node.values())
    if isinstance(node, list):
        return any(_has_ref(item) for item in node)
    return False


@pytest.mark.parametrize("model", REAL_SCHEMAS, ids=lambda m: m.__name__)
def test_portable_schema_strips_refs_from_every_real_response_schema(
    model: type[BaseModel],
) -> None:
    schema = model.model_json_schema()

    result = portable_schema(schema=schema)

    assert "$defs" not in result
    assert not _has_ref(result)


@pytest.mark.parametrize("model", REAL_SCHEMAS, ids=lambda m: m.__name__)
def test_portable_schema_marks_every_object_closed(model: type[BaseModel]) -> None:
    schema = model.model_json_schema()

    result = portable_schema(schema=schema)

    objects = _walk_objects(result)
    assert objects, "expected at least one object node"
    assert all(obj.get("additionalProperties") is False for obj in objects)


def test_portable_schema_removes_unsupported_keywords() -> None:
    schema = {
        "type": "object",
        "title": "Thing",
        "properties": {
            "name": {
                "type": "string",
                "title": "Name",
                "default": "x",
                "examples": ["a"],
                "minLength": 1,
                "maxLength": 10,
                "pattern": "^[a-z]+$",
                "format": "email",
            },
            "count": {
                "type": "integer",
                "minimum": 0,
                "maximum": 10,
                "exclusiveMinimum": -1,
                "exclusiveMaximum": 11,
            },
            "items": {
                "type": "array",
                "minItems": 1,
                "maxItems": 5,
                "uniqueItems": True,
                "items": {"type": "string"},
            },
        },
        "required": ["name"],
    }

    result = portable_schema(schema=schema)

    assert "title" not in result
    name_props = result["properties"]["name"]
    for forbidden in (
        "title",
        "default",
        "examples",
        "minLength",
        "maxLength",
        "pattern",
        "format",
    ):
        assert forbidden not in name_props
    count_props = result["properties"]["count"]
    for forbidden in ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"):
        assert forbidden not in count_props
    items_props = result["properties"]["items"]
    for forbidden in ("minItems", "maxItems", "uniqueItems"):
        assert forbidden not in items_props


def test_portable_schema_inlines_defs_and_resolves_nested_refs() -> None:
    schema = {
        "$defs": {
            "Edit": {
                "type": "object",
                "properties": {"before": {"type": "string"}},
                "required": ["before"],
            }
        },
        "type": "object",
        "properties": {
            "edits": {"type": "array", "items": {"$ref": "#/$defs/Edit"}},
        },
        "required": ["edits"],
    }

    result = portable_schema(schema=schema)

    assert "$defs" not in result
    inlined = result["properties"]["edits"]["items"]
    assert inlined["type"] == "object"
    assert inlined["additionalProperties"] is False
    assert "before" in inlined["properties"]


def test_portable_schema_adds_additional_properties_false_to_root_object() -> None:
    schema = {"type": "object", "properties": {"x": {"type": "string"}}}

    result = portable_schema(schema=schema)

    assert result["additionalProperties"] is False


def test_portable_schema_does_not_mutate_input() -> None:
    schema = {
        "$defs": {"A": {"type": "object", "properties": {}}},
        "type": "object",
        "properties": {"a": {"$ref": "#/$defs/A"}},
    }
    original = {
        "$defs": {"A": {"type": "object", "properties": {}}},
        "type": "object",
        "properties": {"a": {"$ref": "#/$defs/A"}},
    }

    portable_schema(schema=schema)

    assert schema == original


def test_portable_schema_leaves_non_object_schema_untouched_besides_stripping() -> None:
    schema = {"type": "string", "minLength": 2, "title": "Name"}

    result = portable_schema(schema=schema)

    assert result == {"type": "string"}
