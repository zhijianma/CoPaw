# -*- coding: utf-8 -*-
"""Shared HintBlock sources and memory projection metadata helpers."""

from __future__ import annotations

from typing import Any

from agentscope.message import HintBlock, Msg

HINT_PROJECTION_METADATA_KEY = "qwenpaw_hint_projection"
HINT_PROJECTION_SCHEMA_VERSION = 1

HINT_SOURCE_CONTEXT = "qwenpaw:context"
HINT_SOURCE_BACKGROUND_TOOL = "qwenpaw:background-tool"
HINT_SOURCE_LOOP_CONTINUATION = "qwenpaw:loop-continuation"
HINT_SOURCE_MISSION = "qwenpaw:mission"
HINT_SOURCE_SKILL = "qwenpaw:skill"
HINT_SOURCE_UPLOADED_FILE = "qwenpaw:uploaded-file"
HINT_SOURCE_BOOTSTRAP = "qwenpaw:bootstrap"
HINT_SOURCE_RUNTIME_STATE = "qwenpaw:runtime-state"
HINT_SOURCE_SCROLL_CONTEXT = "qwenpaw:scroll-context"

HINT_POSITION_BEFORE_FIRST_TEXT = "before_first_text"
HINT_POSITION_APPEND_TEXT = "append_text"
HINT_POSITION_AFTER_BLOCK_ID = "after_block_id"
HINT_POSITION_REPLACE_CONTENT = "replace_content"


def make_hint_carrier(
    *,
    hint: str | list[Any],
    source: str,
    name: str = "system",
    target_msg_id: str | None = None,
    position: str | None = None,
    anchor_block_id: str | None = None,
    renderer_version: int | None = None,
    renderer_context: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> Msg:
    """Build an assistant HintBlock message with projection metadata."""
    block = HintBlock(hint=hint, source=source)
    msg_metadata: dict[str, Any] = dict(metadata or {})
    entry = {
        key: value
        for key, value in {
            "target_msg_id": target_msg_id,
            "position": position,
            "anchor_block_id": anchor_block_id,
            "renderer_version": renderer_version,
            "renderer_context": renderer_context or {},
        }.items()
        if value not in (None, {})
    }
    if entry:
        msg_metadata[HINT_PROJECTION_METADATA_KEY] = {
            "version": HINT_PROJECTION_SCHEMA_VERSION,
            "blocks": {block.id: entry},
        }
    return Msg(
        name=name,
        role="assistant",
        content=[block],
        metadata=msg_metadata,
    )
