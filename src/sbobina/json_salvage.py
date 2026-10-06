"""The items a model reply wrote in full before it broke off (F40, study blocks).

qwen3.5:9b writes longer than num_predict allows on dense material and stops
inside an item, the same at every attempt. The array under a known key is
decoded item by item; the first item that does not decode ends the scan.
"""

import json
import re
from typing import Any, get_args

from pydantic import BaseModel, ValidationError

_SEPARATORS = " \t\r\n,"


def complete_items(content: str, key: str) -> list[Any]:
    """The JSON values of the `key` array that are complete in `content`."""
    match = re.search(rf'"{re.escape(key)}"\s*:\s*\[', content)
    if match is None:
        return []
    decoder = json.JSONDecoder()
    items: list[Any] = []
    index = match.end()
    while True:
        while index < len(content) and content[index] in _SEPARATORS:
            index += 1
        try:
            item, index = decoder.raw_decode(content, index)
        except json.JSONDecodeError:
            return items
        items.append(item)


def keep_valid(
    items: list[Any], response_model: type[BaseModel], field: str
) -> list[Any]:
    """The items that pass the schema of `field` one by one (F89).

    Validating them together let one closed but malformed item sink the
    complete ones before it.
    """
    item_model = get_args(response_model.model_fields[field].annotation)[0]
    valid = []
    for item in items:
        try:
            item_model.model_validate(item)
        except ValidationError:
            continue
        valid.append(item)
    return valid
