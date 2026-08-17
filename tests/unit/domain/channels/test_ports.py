# -*- coding: utf-8 -*-
"""Channel adapter and delivery port contracts."""

from __future__ import annotations

from typing import Any

from qwenpaw.domain.channels.models import InboundMessage, ReplyTarget
from qwenpaw.domain.channels.ports import (
    ChannelAdapter,
    DeliveryStrategy,
    ReplyEvent,
    ReplyEventType,
)


class _Adapter:
    def normalize(self, native_payload: Any) -> InboundMessage:
        del native_payload
        return InboundMessage(
            "message-1",
            "console:web",
            "user-1",
            "chat-1",
        )


class _Delivery:
    async def deliver(self, event: ReplyEvent) -> None:
        del event


def test_ports_are_runtime_checkable() -> None:
    assert isinstance(_Adapter(), ChannelAdapter)
    assert isinstance(_Delivery(), DeliveryStrategy)


def test_reply_event_copies_metadata() -> None:
    metadata = {"sequence": 1}
    event = ReplyEvent(
        turn_id="turn-1",
        type=ReplyEventType.MESSAGE,
        target=ReplyTarget("console:web", "chat-1"),
        payload="hello",
        metadata=metadata,
    )
    metadata["sequence"] = 2

    assert event.metadata["sequence"] == 1


def test_reply_event_requires_turn_id() -> None:
    try:
        ReplyEvent(
            turn_id="",
            type=ReplyEventType.COMPLETED,
            target=ReplyTarget("console:web", "chat-1"),
        )
    except ValueError as error:
        assert "turn_id" in str(error)
    else:
        raise AssertionError("ReplyEvent accepted an empty turn_id")
