# -*- coding: utf-8 -*-
"""Composition root for bundled protocols."""

from __future__ import annotations

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


__all__ = ["get_protocol_registry"]
