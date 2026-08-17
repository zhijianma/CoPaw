# -*- coding: utf-8 -*-
"""Transport-neutral channel endpoint and message models."""

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
class ChannelEndpoint:
    """One configured external account or Web entry surface."""

    endpoint_id: str
    channel_key: str
    account_id: str
    enabled: bool = True
    settings: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_identity(
            self,
            "endpoint_id",
            "channel_key",
            "account_id",
        )
        object.__setattr__(
            self,
            "settings",
            MappingProxyType(dict(self.settings)),
        )


@dataclass(frozen=True, slots=True)
class AgentBinding:
    """Assign an endpoint to an agent without changing the endpoint."""

    binding_id: str
    endpoint_id: str
    agent_id: str
    enabled: bool = True
    priority: int = 0

    def __post_init__(self) -> None:
        _require_identity(
            self,
            "binding_id",
            "endpoint_id",
            "agent_id",
        )


@dataclass(frozen=True, slots=True)
class ReplyTarget:
    """Opaque destination understood only by the originating adapter."""

    endpoint_id: str
    conversation_id: str
    thread_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_identity(self, "endpoint_id", "conversation_id")
        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(dict(self.metadata)),
        )


@dataclass(frozen=True, slots=True)
class InboundMessage:
    """Normalized user input emitted by a channel adapter."""

    message_id: str
    endpoint_id: str
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
            "endpoint_id",
            "sender_id",
            "conversation_id",
        )
        object.__setattr__(self, "content", tuple(self.content))
        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(dict(self.metadata)),
        )


@dataclass(frozen=True, slots=True)
class ChannelRoute:
    """Resolved delivery path from one endpoint to one agent."""

    endpoint_id: str
    binding_id: str
    agent_id: str
    conversation_id: str

    def __post_init__(self) -> None:
        _require_identity(
            self,
            "endpoint_id",
            "binding_id",
            "agent_id",
            "conversation_id",
        )


__all__ = [
    "AgentBinding",
    "ChannelEndpoint",
    "ChannelRoute",
    "InboundMessage",
    "ReplyTarget",
]
