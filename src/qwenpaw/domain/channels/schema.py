# -*- coding: utf-8 -*-
"""Shared Channel configuration schema projections.

Pydantic models are the authoritative contract.  UI and CLI field metadata
are projections so built-in and plugin Channels do not maintain a second
hand-written list of configuration keys.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel
from pydantic_core import PydanticUndefined

_SECRET_NAME_RE = re.compile(
    r"(?:secret|token|password|private[_-]?key|auth)",
    re.IGNORECASE,
)


def is_channel_secret_field(name: str) -> bool:
    """Return whether a setting name should be treated as sensitive."""
    return bool(_SECRET_NAME_RE.search(name))


def _effective_field_schema(
    field_schema: dict[str, Any],
    definitions: dict[str, Any],
) -> dict[str, Any]:
    """Resolve nullable unions and local refs for form type selection."""
    resolved = dict(field_schema)
    reference = resolved.get("$ref")
    if isinstance(reference, str) and reference.startswith("#/$defs/"):
        target = definitions.get(reference.removeprefix("#/$defs/"), {})
        resolved = {**target, **resolved}
        resolved.pop("$ref", None)

    for union_key in ("anyOf", "oneOf"):
        candidates = resolved.get(union_key)
        if not isinstance(candidates, list):
            continue
        selected = next(
            (
                item
                for item in candidates
                if isinstance(item, dict) and item.get("type") != "null"
            ),
            {},
        )
        parent = dict(resolved)
        parent.pop(union_key, None)
        return {
            **_effective_field_schema(selected, definitions),
            **parent,
        }
    return resolved


def channel_config_fields_from_model(
    model: type[BaseModel],
    *,
    include_enabled: bool = False,
) -> list[dict[str, Any]]:
    """Project a Channel config model into the legacy form-field protocol."""
    schema = model.model_json_schema()
    required = set(schema.get("required") or ())
    properties = schema.get("properties") or {}
    definitions = schema.get("$defs") or {}
    result: list[dict[str, Any]] = []
    for name, model_field in model.model_fields.items():
        if name == "enabled" and not include_enabled:
            continue
        field_schema = _effective_field_schema(
            dict(properties.get(name) or {}),
            definitions,
        )
        schema_type = field_schema.get("type", "string")
        if isinstance(schema_type, list):
            schema_type = next(
                (item for item in schema_type if item != "null"),
                "string",
            )
        options = list(field_schema.get("enum") or ())
        if options:
            field_type = "select"
        elif is_channel_secret_field(name):
            field_type = "password"
        else:
            field_type = {
                "boolean": "switch",
                "integer": "number",
                "number": "number",
            }.get(str(schema_type), "text")
        item: dict[str, Any] = {
            "name": name,
            "label": str(
                field_schema.get("title") or name.replace("_", " ").title()
            ),
            "type": field_type,
            "schema_type": str(schema_type),
            "required": name in required,
        }
        default = field_schema.get("default", model_field.default)
        if default is not PydanticUndefined:
            item["default"] = default
        description = field_schema.get("description")
        if description:
            item["help"] = str(description)
        if options:
            item["options"] = options
        result.append(item)
    return result
