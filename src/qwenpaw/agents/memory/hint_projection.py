# -*- coding: utf-8 -*-
"""Build the pre-HintBlock-compatible view used by memory backends."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from copy import deepcopy
from typing import Any

from agentscope.message import HintBlock, Msg, TextBlock

from ..hints import (
    HINT_POSITION_AFTER_BLOCK_ID,
    HINT_POSITION_APPEND_TEXT,
    HINT_POSITION_BEFORE_FIRST_TEXT,
    HINT_POSITION_REPLACE_CONTENT,
    HINT_PROJECTION_METADATA_KEY,
    HINT_PROJECTION_SCHEMA_VERSION,
    HINT_SOURCE_BACKGROUND_TOOL,
    HINT_SOURCE_BOOTSTRAP,
    HINT_SOURCE_CONTEXT,
    HINT_SOURCE_LOOP_CONTINUATION,
    HINT_SOURCE_MISSION,
    HINT_SOURCE_RUNTIME_STATE,
    HINT_SOURCE_SCROLL_CONTEXT,
    HINT_SOURCE_SKILL,
    HINT_SOURCE_UPLOADED_FILE,
)
from ...modes.mission.handler import render_legacy_mission_content

logger = logging.getLogger(__name__)

ACTION_EXPAND = "expand_same_message"
ACTION_MERGE = "merge_target_user"
ACTION_REPLACE = "replace_target_user"
ACTION_EXCLUDE = "exclude_as_before"

SOURCE_ACTIONS = {
    HINT_SOURCE_BACKGROUND_TOOL: ACTION_EXPAND,
    HINT_SOURCE_CONTEXT: ACTION_EXCLUDE,
    HINT_SOURCE_LOOP_CONTINUATION: ACTION_EXCLUDE,
    HINT_SOURCE_MISSION: ACTION_REPLACE,
    HINT_SOURCE_SKILL: ACTION_MERGE,
    HINT_SOURCE_UPLOADED_FILE: ACTION_MERGE,
    HINT_SOURCE_BOOTSTRAP: ACTION_MERGE,
    HINT_SOURCE_RUNTIME_STATE: ACTION_EXCLUDE,
    HINT_SOURCE_SCROLL_CONTEXT: ACTION_EXCLUDE,
}

LegacyRenderer = Callable[[Msg, HintBlock, dict[str, Any]], list[Any]]
_LEGACY_RENDERERS: dict[str, LegacyRenderer] = {
    HINT_SOURCE_MISSION: render_legacy_mission_content,
}


def register_legacy_hint_renderer(
    source: str,
    renderer: LegacyRenderer,
) -> None:
    """Register the renderer for a replace-target projection source."""
    _LEGACY_RENDERERS[source] = renderer


def _legacy_renderer(source: str) -> LegacyRenderer | None:
    return _LEGACY_RENDERERS.get(source)


def _has_hint(messages: Sequence[Msg]) -> bool:
    return any(
        isinstance(block, HintBlock)
        for msg in messages
        for block in msg.content
    )


def _expanded_blocks(block: HintBlock) -> list[Any]:
    if isinstance(block.hint, str):
        return [
            TextBlock(
                id=block.id,
                text=block.hint,
                created_at=block.created_at,
                finished_at=block.finished_at,
            ),
        ]
    return list(block.hint)


def _projection_entry(msg: Msg, block: HintBlock) -> dict[str, Any] | None:
    projection = msg.metadata.get(HINT_PROJECTION_METADATA_KEY)
    if not isinstance(projection, dict):
        return None
    if projection.get("version") != HINT_PROJECTION_SCHEMA_VERSION:
        return None
    blocks = projection.get("blocks")
    if not isinstance(blocks, dict):
        return None
    entry = blocks.get(block.id)
    return entry if isinstance(entry, dict) else None


def _fallback(
    msg: Msg,
    block: HintBlock,
    reason: str,
) -> list[Any]:
    logger.warning(
        "Expanding HintBlock for memory because %s: source=%r "
        "message_id=%s block_id=%s",
        reason,
        block.source,
        msg.id,
        block.id,
    )
    return _expanded_blocks(block)


# pylint: disable=too-many-return-statements
def _insert_target_blocks(
    target: Msg,
    blocks: list[Any],
    entry: dict[str, Any],
) -> bool:
    position = entry.get("position")
    if position == HINT_POSITION_APPEND_TEXT:
        if all(isinstance(block, TextBlock) for block in blocks):
            for item in reversed(target.content):
                if isinstance(item, TextBlock):
                    item.text += "".join(block.text for block in blocks)
                    return True
        target.content.extend(blocks)
        return True
    if position == HINT_POSITION_BEFORE_FIRST_TEXT:
        if all(isinstance(block, TextBlock) for block in blocks):
            for item in target.content:
                if isinstance(item, TextBlock):
                    item.text = (
                        "".join(block.text for block in blocks) + item.text
                    )
                    return True
        target.content[0:0] = blocks
        return True
    if position == HINT_POSITION_AFTER_BLOCK_ID:
        anchor = entry.get("anchor_block_id")
        for idx, item in enumerate(target.content):
            if getattr(item, "id", None) == anchor:
                target.content[idx + 1:idx + 1] = blocks
                return True
        return False
    return False


# pylint: disable=too-many-branches
def project_messages_for_memory(messages: Sequence[Msg]) -> list[Msg]:
    """Return the pre-migration-equivalent memory view.

    Messages without HintBlocks take a zero-copy fast path. Any projected
    input is deep-copied so live context, snapshots, and Scroll stay intact.
    """
    if not _has_hint(messages):
        return list(messages)

    projected = deepcopy(list(messages))
    by_id = {msg.id: msg for msg in projected}
    kept_messages: list[Msg] = []

    for msg in projected:
        new_content: list[Any] = []
        for block in msg.content:
            if not isinstance(block, HintBlock):
                new_content.append(block)
                continue

            action = SOURCE_ACTIONS.get(block.source)
            if action is None:
                new_content.extend(
                    _fallback(msg, block, "the source is unknown"),
                )
                continue
            if action == ACTION_EXPAND:
                new_content.extend(_expanded_blocks(block))
                continue
            if action == ACTION_EXCLUDE:
                continue

            entry = _projection_entry(msg, block)
            target_id = entry.get("target_msg_id") if entry else None
            target = by_id.get(target_id) if target_id else None
            if target is None or target.role != "user":
                new_content.extend(
                    _fallback(msg, block, "target user metadata is missing"),
                )
                continue

            if action == ACTION_MERGE:
                if not _insert_target_blocks(
                    target,
                    _expanded_blocks(block),
                    entry or {},
                ):
                    new_content.extend(
                        _fallback(msg, block, "the merge position is invalid"),
                    )
                continue

            renderer = _legacy_renderer(block.source)
            if (
                action != ACTION_REPLACE
                or entry is None
                or entry.get("position") != HINT_POSITION_REPLACE_CONTENT
                or renderer is None
            ):
                new_content.extend(
                    _fallback(msg, block, "the legacy renderer is missing"),
                )
                continue
            try:
                target.content = renderer(target, block, entry)
            except Exception:
                logger.exception(
                    "Legacy HintBlock renderer failed: source=%r block_id=%s",
                    block.source,
                    block.id,
                )
                raise

        msg.content = new_content
        if msg.content:
            kept_messages.append(msg)

    return kept_messages
