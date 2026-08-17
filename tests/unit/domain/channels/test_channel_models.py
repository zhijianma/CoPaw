# -*- coding: utf-8 -*-
"""Tests for Channel request models."""

from __future__ import annotations

import pytest

from qwenpaw.domain.channels.models import InboundMessage, ReplyTarget
from qwenpaw.domain.channels.routing import build_turn_request


def test_build_turn_request_preserves_channel_and_session_identity() -> None:
    target = ReplyTarget("telegram", "chat-1")
    inbound = InboundMessage(
        message_id="message-1",
        channel_type="telegram",
        sender_id="user-1",
        conversation_id="chat-1",
        content=("hello",),
        reply_target=target,
        metadata={"tenant": "acme"},
    )

    request = build_turn_request(inbound, "sales", turn_id="turn-1")

    assert request.agent_id == "sales"
    assert request.session_id == "chat-1"
    assert request.source.channel_type == "telegram"
    assert request.reply_target is target
    assert request.context["tenant"] == "acme"


@pytest.mark.parametrize(
    "field",
    ["message_id", "channel_type", "sender_id", "conversation_id"],
)
def test_inbound_message_rejects_empty_identity(field: str) -> None:
    values = {
        "message_id": "message-1",
        "channel_type": "telegram",
        "sender_id": "user-1",
        "conversation_id": "chat-1",
    }
    values[field] = ""

    with pytest.raises(ValueError, match=field):
        InboundMessage(**values)
