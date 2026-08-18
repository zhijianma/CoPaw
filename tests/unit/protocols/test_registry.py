# -*- coding: utf-8 -*-
"""Protocol extensions are registered without modifying Runtime core."""

from __future__ import annotations

from typing import Any, AsyncIterator

import pytest

from qwenpaw.domain.turns.events import RuntimeEvent
from qwenpaw.protocols.ports import PresentationContext
from qwenpaw.protocols.registry import ProtocolRegistration, ProtocolRegistry


class DemoPresenter:
    async def present(
        self,
        event: RuntimeEvent,
        context: PresentationContext,
    ) -> AsyncIterator[Any]:
        yield (context.protocol, event.type.value)


def test_protocol_registry_creates_presenter_from_registration() -> None:
    registry = ProtocolRegistry()
    registry.register(
        ProtocolRegistration(
            key="demo",
            presenter_factory=lambda _context: DemoPresenter(),
        ),
    )
    context = PresentationContext(protocol="demo", conversation_id="c-1")

    presenter = registry.create_presenter(context)

    assert isinstance(presenter, DemoPresenter)


def test_protocol_registry_rejects_duplicate_keys() -> None:
    registry = ProtocolRegistry()
    registration = ProtocolRegistration(
        key="demo",
        presenter_factory=lambda _context: DemoPresenter(),
    )
    registry.register(registration)

    with pytest.raises(ValueError, match="already registered"):
        registry.register(registration)
