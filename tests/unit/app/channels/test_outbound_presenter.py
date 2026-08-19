# -*- coding: utf-8 -*-
"""Tests for canonical proactive Channel presentation."""

from qwenpaw.app.channels.outbound import ChannelOutboundPresenter
from qwenpaw.domain.channels.ports import ReplyEvent, ReplyEventType
from qwenpaw.domain.turns.events import RuntimeEvent


def test_outbound_presenter_preserves_reply_target() -> None:
    presenter = ChannelOutboundPresenter(
        channel_type="feishu-backup",
        conversation_id="chat-1",
        recipient_id="user-1",
        metadata={"tenant": "acme"},
    )

    replies = list(
        presenter.present(RuntimeEvent.message("hello", turn_id="turn-1")),
    )

    assert replies
    assert all(isinstance(reply, ReplyEvent) for reply in replies)
    reply = replies[-1]
    assert reply.type is ReplyEventType.MESSAGE
    assert reply.target.channel_type == "feishu-backup"
    assert reply.target.conversation_id == "chat-1"
    assert reply.target.recipient_id == "user-1"
    assert reply.target.metadata["tenant"] == "acme"
