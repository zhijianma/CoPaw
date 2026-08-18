# -*- coding: utf-8 -*-
"""Ports owned by semantic protocols, independent of connectivity."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, AsyncIterator, Mapping, Protocol

from ..domain.turns.events import RuntimeEvent
from ..domain.turns.models import TurnRequest


@dataclass(frozen=True, slots=True)
class PresentationContext:
    """Addressing data used by a protocol presenter."""

    protocol: str
    conversation_id: str
    turn_id: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.protocol.strip():
            raise ValueError("protocol must not be empty")
        object.__setattr__(
            self, "metadata", MappingProxyType(dict(self.metadata))
        )


class TurnIngress(Protocol):
    """Decode one protocol request into the runtime command model."""

    def decode(self, request: Any) -> TurnRequest:
        """Decode a protocol-native request."""


class TurnEventPresenter(Protocol):
    """Encode runtime facts into protocol-native output frames."""

    def present(
        self,
        event: RuntimeEvent,
        context: PresentationContext,
    ) -> AsyncIterator[Any]:
        """Present one canonical runtime event."""


__all__ = ["PresentationContext", "TurnEventPresenter", "TurnIngress"]
