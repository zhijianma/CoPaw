# -*- coding: utf-8 -*-
"""Composition root for bundled protocols."""

from __future__ import annotations

from typing import Any

from .ports import PresentationContext, TurnEventPresenter
from .registry import ProtocolRegistration, ProtocolRegistry

_CONSOLE_PROTOCOL = "console"
_REGISTRY: ProtocolRegistry | None = None


def get_protocol_registry() -> ProtocolRegistry:
    """Return the lazily composed built-in protocol registry."""
    global _REGISTRY  # pylint: disable=global-statement
    if _REGISTRY is None:
        from .console import ConsoleEventPresenter, ConsoleTurnIngress

        registry = ProtocolRegistry()
        registry.register(
            ProtocolRegistration(
                key=_CONSOLE_PROTOCOL,
                presenter_factory=lambda context: ConsoleEventPresenter(
                    session_id=context.conversation_id,
                ),
                ingress_factory=ConsoleTurnIngress,
            ),
        )
        _REGISTRY = registry
    return _REGISTRY


def create_default_presenter(
    *,
    conversation_id: str,
    turn_id: str = "",
    metadata: dict[str, Any] | None = None,
) -> tuple[TurnEventPresenter, PresentationContext]:
    """Resolve the legacy WebUI response protocol outside Runtime core."""
    context = PresentationContext(
        protocol=_CONSOLE_PROTOCOL,
        conversation_id=conversation_id,
        turn_id=turn_id,
        metadata=metadata or {},
    )
    return get_protocol_registry().create_presenter(context), context


__all__ = ["create_default_presenter", "get_protocol_registry"]
