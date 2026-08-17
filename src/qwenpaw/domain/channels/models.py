# -*- coding: utf-8 -*-
"""Transport-neutral Channel message models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Mapping, Sequence


def _require_identity(instance: Any, *names: str) -> None:
    for name in names:
        if not str(getattr(instance, name, "") or "").strip():
            raise ValueError(f"{name} must not be empty")


@dataclass(frozen=True, slots=True)
class ReplyTarget:
    """Opaque destination understood only by one Channel type."""

    channel_type: str
    conversation_id: str
    thread_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_identity(
            self,
            "channel_type",
            "conversation_id",
        )
        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(dict(self.metadata)),
        )


@dataclass(frozen=True, slots=True)
class InboundMessage:
    """Normalized user input emitted by a Channel."""

    message_id: str
    channel_type: str
    sender_id: str
    conversation_id: str
    content: Sequence[Any] = field(default_factory=tuple)
    reply_target: ReplyTarget | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    occurred_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc),
    )

    def __post_init__(self) -> None:
        _require_identity(
            self,
            "message_id",
            "channel_type",
            "sender_id",
            "conversation_id",
        )
        object.__setattr__(self, "content", tuple(self.content))
        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(dict(self.metadata)),
        )


__all__ = ["InboundMessage", "ReplyTarget"]
