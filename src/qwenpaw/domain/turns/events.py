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
    AGENT_EVENT = "agent_event"
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
    payload: Any = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    occurred_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc),
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(dict(self.metadata)),
        )

    @classmethod
    def agent_event(
        cls,
        payload: Any,
        *,
        turn_id: str = "",
    ) -> "RuntimeEvent":
        """Wrap one native AgentScope event without translating it."""
        return cls(
            type=RuntimeEventType.AGENT_EVENT,
            turn_id=turn_id,
            payload=payload,
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
