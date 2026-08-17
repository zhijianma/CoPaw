# -*- coding: utf-8 -*-
"""Project runtime facts into transport-neutral outbound reply events."""

from __future__ import annotations

from ..domain.channels.models import ReplyTarget
from ..domain.channels.ports import ReplyEvent, ReplyEventType
from ..domain.turns.events import RuntimeEvent, RuntimeEventType


_REPLY_EVENT_TYPES = {
    RuntimeEventType.TURN_STARTED: ReplyEventType.STARTED,
    RuntimeEventType.AGENT_EVENT: ReplyEventType.CONTENT,
    RuntimeEventType.HEARTBEAT: ReplyEventType.HEARTBEAT,
    RuntimeEventType.MESSAGE: ReplyEventType.MESSAGE,
    RuntimeEventType.TURN_COMPLETED: ReplyEventType.COMPLETED,
    RuntimeEventType.TURN_FAILED: ReplyEventType.FAILED,
    RuntimeEventType.TURN_CANCELLED: ReplyEventType.CANCELLED,
}


class ReplyProjector:
    """Attach one adapter-owned target to a Runtime event stream."""

    def __init__(self, target: ReplyTarget) -> None:
        self.target = target

    def project(self, event: RuntimeEvent) -> ReplyEvent:
        """Project one Runtime event without platform-specific conversion."""
        try:
            reply_type = _REPLY_EVENT_TYPES[event.type]
        except KeyError as error:
            raise ValueError(
                f"Unsupported runtime event type: {event.type}",
            ) from error
        return ReplyEvent(
            turn_id=event.turn_id,
            type=reply_type,
            target=self.target,
            payload=event.payload,
            metadata=event.metadata,
        )


__all__ = ["ReplyProjector"]
