# -*- coding: utf-8 -*-
"""Protocol-neutral buffering for multipart inbound turns."""

from __future__ import annotations

import logging
from typing import Any

from ..schemas import ContentType

logger = logging.getLogger(__name__)


def content_has_text(contents: list[Any] | None) -> bool:
    """Return whether content contains non-empty text or refusal input."""
    for content in contents or []:
        content_type = getattr(content, "type", None)
        if content_type == ContentType.TEXT and str(
            getattr(content, "text", "") or "",
        ).strip():
            return True
        if content_type == ContentType.REFUSAL and str(
            getattr(content, "refusal", "") or "",
        ).strip():
            return True
    return False


def content_has_audio(contents: list[Any] | None) -> bool:
    """Return whether content contains at least one audio block."""
    return any(
        getattr(content, "type", None) == ContentType.AUDIO
        for content in contents or []
    )


def apply_no_text_debounce(
    *,
    session_id: str,
    content_parts: list[Any],
    enabled: bool,
    pending_by_session: dict[str, list[Any]],
) -> tuple[bool, list[Any]]:
    """Buffer attachment-only fragments until a text fragment arrives."""
    if not enabled:
        pending = pending_by_session.pop(session_id, [])
        return True, pending + list(content_parts)
    if not content_has_text(content_parts):
        if content_has_audio(content_parts):
            pending = pending_by_session.pop(session_id, [])
            return True, pending + list(content_parts)
        pending_by_session.setdefault(session_id, []).extend(content_parts)
        logger.debug(
            "inbound debounce: no text, buffered session_id=%s",
            session_id[:24] if session_id else "",
        )
        return False, []
    pending = pending_by_session.pop(session_id, [])
    return True, pending + list(content_parts)


__all__ = [
    "apply_no_text_debounce",
    "content_has_audio",
    "content_has_text",
]
