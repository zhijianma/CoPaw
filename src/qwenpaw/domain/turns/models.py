# -*- coding: utf-8 -*-
"""Transport-neutral request models for one agent turn."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Literal, Mapping, Sequence

RequestSourceKind = Literal[
    "console",
    "channel",
    "cron",
    "approval",
    "system",
]

_REQUEST_SOURCE_KINDS = frozenset(
    {
        "console",
        "channel",
        "cron",
        "approval",
        "system",
    },
)


@dataclass(frozen=True, slots=True)
class RequestSource:
    """Describe where a turn entered the application core."""

    kind: RequestSourceKind
    channel_type: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in _REQUEST_SOURCE_KINDS:
            raise ValueError(f"Unsupported request source kind: {self.kind}")


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
