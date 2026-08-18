# -*- coding: utf-8 -*-
"""Transport-neutral events emitted while an agent turn is running."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping


class RuntimeEventType(str, Enum):
    """Stable event categories exposed by the runtime core."""

    TURN_STARTED = "turn_started"
    REPLY_STARTED = "reply_started"
    REPLY_COMPLETED = "reply_completed"
    MODEL_CALL_STARTED = "model_call_started"
    MODEL_CALL_COMPLETED = "model_call_completed"
    CONTENT_STARTED = "content_started"
    CONTENT_DELTA = "content_delta"
    CONTENT_COMPLETED = "content_completed"
    TOOL_CALL_STARTED = "tool_call_started"
    TOOL_CALL_DELTA = "tool_call_delta"
    TOOL_CALL_COMPLETED = "tool_call_completed"
    TOOL_RESULT_STARTED = "tool_result_started"
    TOOL_RESULT_DELTA = "tool_result_delta"
    TOOL_RESULT_COMPLETED = "tool_result_completed"
    INTERACTION_REQUIRED = "interaction_required"
    INTERACTION_RESULT = "interaction_result"
    LIMIT_REACHED = "limit_reached"
    CUSTOM = "custom"
    HEARTBEAT = "heartbeat"
    MESSAGE = "message"
    TURN_COMPLETED = "turn_completed"
    TURN_FAILED = "turn_failed"
    TURN_CANCELLED = "turn_cancelled"


@dataclass(frozen=True, slots=True)
class RuntimeEvent:
    """One runtime fact with no Console or platform presentation fields."""

    type: RuntimeEventType
    turn_id: str = ""
    data: Mapping[str, Any] = field(default_factory=dict)
    payload: Any = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    occurred_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc),
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "data",
            MappingProxyType(dict(self.data)),
        )
        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(dict(self.metadata)),
        )

    @classmethod
    def canonical(
        cls,
        event_type: RuntimeEventType,
        *,
        turn_id: str = "",
        data: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "RuntimeEvent":
        """Create a normalized engine-independent runtime event."""
        return cls(
            type=event_type,
            turn_id=turn_id,
            data=data or {},
            metadata=metadata or {},
        )

    @classmethod
    def turn_started(cls, *, turn_id: str = "") -> "RuntimeEvent":
        """Create the event that opens one runtime turn."""
        return cls(
            type=RuntimeEventType.TURN_STARTED,
            turn_id=turn_id,
        )

    @classmethod
    def heartbeat(cls, *, turn_id: str = "") -> "RuntimeEvent":
        """Create a transport-neutral keep-alive event."""
        return cls(
            type=RuntimeEventType.HEARTBEAT,
            turn_id=turn_id,
        )

    @classmethod
    def message(
        cls,
        payload: Any,
        *,
        turn_id: str = "",
    ) -> "RuntimeEvent":
        """Create an event for a runtime-produced complete message."""
        return cls(
            type=RuntimeEventType.MESSAGE,
            turn_id=turn_id,
            payload=payload,
        )

    @classmethod
    def turn_completed(cls, *, turn_id: str = "") -> "RuntimeEvent":
        """Create the terminal success event for a turn."""
        return cls(
            type=RuntimeEventType.TURN_COMPLETED,
            turn_id=turn_id,
        )

    @classmethod
    def turn_failed(
        cls,
        error_text: str,
        error_code: str = "error",
        *,
        turn_id: str = "",
    ) -> "RuntimeEvent":
        """Create the terminal failure event for a turn."""
        return cls(
            type=RuntimeEventType.TURN_FAILED,
            turn_id=turn_id,
            payload=RuntimeFailure(
                error_text=error_text,
                error_code=error_code,
            ),
        )

    @classmethod
    def turn_cancelled(cls, *, turn_id: str = "") -> "RuntimeEvent":
        """Create the terminal cancellation event for a turn."""
        return cls(
            type=RuntimeEventType.TURN_CANCELLED,
            turn_id=turn_id,
        )


@dataclass(frozen=True, slots=True)
class RuntimeFailure:
    """Transport-neutral details for a failed turn."""

    error_text: str
    error_code: str = "error"


@dataclass(frozen=True, slots=True)
class EventRecord:
    """Attach a replay cursor without mutating the domain event."""

    cursor: int
    event: RuntimeEvent

    def __post_init__(self) -> None:
        if self.cursor < 0:
            raise ValueError(f"cursor must be non-negative: {self.cursor}")


__all__ = [
    "EventRecord",
    "RuntimeEvent",
    "RuntimeEventType",
    "RuntimeFailure",
]
