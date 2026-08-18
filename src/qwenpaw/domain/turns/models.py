# -*- coding: utf-8 -*-
"""Transport-neutral request models for one agent turn."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping, Sequence

RequestSourceKind = str


@dataclass(frozen=True, slots=True, init=False)
class RequestSource:
    """Describe where a turn entered the application core."""

    protocol: str
    endpoint_id: str | None
    channel_type: str | None = None

    def __init__(
        self,
        protocol: str | None = None,
        endpoint_id: str | None = None,
        channel_type: str | None = None,
        *,
        kind: str | None = None,
    ) -> None:
        """Accept open protocol keys and the legacy ``kind`` spelling."""
        value = str(protocol or kind or "").strip()
        if not value:
            raise ValueError("protocol must not be empty")
        object.__setattr__(self, "protocol", value)
        object.__setattr__(self, "endpoint_id", endpoint_id)
        object.__setattr__(self, "channel_type", channel_type)

    @property
    def kind(self) -> str:
        """Legacy alias retained for callers during the boundary migration."""
        return self.protocol


@dataclass(frozen=True, slots=True)
class TurnRequest:
    """A validated request that is independent of any transport schema."""

    turn_id: str
    agent_id: str
    session_id: str
    user_id: str
    messages: Sequence[Any]
    source: RequestSource
    reply_target: Any | None = None
    context: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("turn_id", "agent_id", "session_id"):
            if not str(getattr(self, name) or "").strip():
                raise ValueError(f"{name} must not be empty")

        object.__setattr__(self, "messages", tuple(self.messages))
        object.__setattr__(
            self,
            "context",
            MappingProxyType(dict(self.context)),
        )


__all__ = ["RequestSource", "RequestSourceKind", "TurnRequest"]
