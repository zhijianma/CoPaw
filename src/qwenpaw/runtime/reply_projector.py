# -*- coding: utf-8 -*-
"""Project runtime facts into transport-neutral outbound reply events."""

from __future__ import annotations

from ..domain.channels.models import ReplyTarget
from ..domain.channels.ports import ReplyEvent, ReplyEventType
from ..domain.turns.events import RuntimeEvent, RuntimeEventType

_REPLY_EVENT_TYPES = {
    RuntimeEventType.TURN_STARTED: ReplyEventType.STARTED,
    RuntimeEventType.HEARTBEAT: ReplyEventType.HEARTBEAT,
    RuntimeEventType.MESSAGE: ReplyEventType.MESSAGE,
    RuntimeEventType.TURN_COMPLETED: ReplyEventType.COMPLETED,
    RuntimeEventType.TURN_FAILED: ReplyEventType.FAILED,
    RuntimeEventType.TURN_CANCELLED: ReplyEventType.CANCELLED,
}

_CONTENT_EVENT_TYPES = frozenset(
    {
        RuntimeEventType.REPLY_STARTED,
        RuntimeEventType.REPLY_COMPLETED,
        RuntimeEventType.MODEL_CALL_STARTED,
        RuntimeEventType.MODEL_CALL_COMPLETED,
        RuntimeEventType.CONTENT_STARTED,
        RuntimeEventType.CONTENT_DELTA,
        RuntimeEventType.CONTENT_COMPLETED,
        RuntimeEventType.TOOL_CALL_STARTED,
        RuntimeEventType.TOOL_CALL_DELTA,
        RuntimeEventType.TOOL_CALL_COMPLETED,
        RuntimeEventType.TOOL_RESULT_STARTED,
        RuntimeEventType.TOOL_RESULT_DELTA,
        RuntimeEventType.TOOL_RESULT_COMPLETED,
        RuntimeEventType.INTERACTION_REQUIRED,
        RuntimeEventType.INTERACTION_RESULT,
        RuntimeEventType.LIMIT_REACHED,
        RuntimeEventType.CUSTOM,
    },
)


class ReplyProjector:
    """Attach one adapter-owned target to a Runtime event stream."""

    def __init__(self, target: ReplyTarget) -> None:
        self.target = target

    def project(self, event: RuntimeEvent) -> ReplyEvent:
        """Project one Runtime event without platform-specific conversion."""
        if event.type in _CONTENT_EVENT_TYPES:
            reply_type = ReplyEventType.CONTENT
            payload = event
        else:
            try:
                reply_type = _REPLY_EVENT_TYPES[event.type]
            except KeyError as error:
                raise ValueError(
                    f"Unsupported runtime event type: {event.type}",
                ) from error
            payload = event.payload
        return ReplyEvent(
            turn_id=event.turn_id,
            type=reply_type,
            target=self.target,
            payload=payload,
            metadata=event.metadata,
        )


__all__ = ["ReplyProjector"]
