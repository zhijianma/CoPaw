# -*- coding: utf-8 -*-
"""Adapt legacy runtime events into transport-neutral reply events."""

from __future__ import annotations

from typing import Any

from ..domain.channels.models import ReplyTarget
from ..domain.channels.ports import ReplyEvent, ReplyEventType


class LegacyReplyAdapter:
    """Project the pre-V2 event stream during compatibility migration."""

    def __init__(self, turn_id: str, target: ReplyTarget) -> None:
        self._turn_id = turn_id
        self._target = target

    def project(self, event: Any) -> ReplyEvent:
        """Classify one legacy event without platform-specific behavior."""
        event_type = ReplyEventType.CONTENT
        obj = getattr(event, "object", None)
        if obj == "message":
            event_type = ReplyEventType.MESSAGE
        elif obj == "response":
            event_type = (
                ReplyEventType.FAILED
                if getattr(event, "error", None)
                else ReplyEventType.COMPLETED
            )
        return ReplyEvent(
            turn_id=self._turn_id,
            type=event_type,
            target=self._target,
            payload=event,
        )


__all__ = ["LegacyReplyAdapter"]
