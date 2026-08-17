# -*- coding: utf-8 -*-
"""Ports implemented by inbound adapters and outbound delivery strategies."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Protocol, runtime_checkable

from .models import InboundMessage, ReplyTarget


class ReplyEventType(str, Enum):
    """Transport-neutral categories understood by delivery strategies."""

    STARTED = "started"
    CONTENT = "content"
    HEARTBEAT = "heartbeat"
    MESSAGE = "message"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class ReplyEvent:
    """One outbound fact associated with an opaque reply target."""

    turn_id: str
    type: ReplyEventType
    target: ReplyTarget
    payload: Any = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.turn_id or "").strip():
            raise ValueError("turn_id must not be empty")
        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(dict(self.metadata)),
        )


@runtime_checkable
class ChannelAdapter(Protocol):
    """Normalize one platform-native payload at the application edge."""

    def normalize(self, native_payload: Any) -> InboundMessage:
        """Convert a native payload into an inbound domain message."""


@runtime_checkable
class DeliveryStrategy(Protocol):
    """Deliver reply events without exposing platform APIs to Runtime."""

    async def deliver(self, event: ReplyEvent) -> None:
        """Deliver one event to its adapter-owned reply target."""


__all__ = [
    "ChannelAdapter",
    "DeliveryStrategy",
    "ReplyEvent",
    "ReplyEventType",
]
