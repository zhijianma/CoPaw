# -*- coding: utf-8 -*-
"""Tests for direct Channel turn routing."""

from qwenpaw.app.channels.turn import ChannelTurn
from qwenpaw.domain.channels.models import ReplyTarget
from qwenpaw.schemas import Message, Role, TextContent


def _request() -> ChannelTurn:
    return ChannelTurn(
        session_id="chat-42",
        sender_id="user-7",
        channel_type="telegram",
        messages=[
            Message(
                role=Role.USER,
                content=[TextContent(text="hello")],
            ),
        ],
        message_id="message-9",
        metadata={
            "conversation_id": "chat-42",
            "thread_id": "thread-3",
            "tenant": "acme",
        },
    )


def test_bridge_preserves_logical_session_identity() -> None:
    turn = _request().to_request(
        agent_id="sales",
        instance_id="telegram",
        runtime_session_id="chat-42",
        channel_instance=None,
    )

    assert turn.turn_id == "message-9"
    assert turn.agent_id == "sales"
    assert turn.session_id == "chat-42"
    assert turn.user_id == "user-7"
    assert turn.source.channel_type == "telegram"
    assert turn.context["tenant"] == "acme"
    assert isinstance(turn.reply_target, ReplyTarget)
    assert turn.reply_target.channel_type == "telegram"
    assert turn.reply_target.conversation_id == "chat-42"
    assert turn.reply_target.thread_id == "thread-3"
    assert turn.messages[0].content[0].text == "hello"


def test_bridge_preserves_an_explicit_reply_target() -> None:
    request = _request()
    target = ReplyTarget(
        channel_type="telegram",
        conversation_id="override",
    )
    request.metadata["reply_target"] = target
    request.metadata["conversation_id"] = "override"

    turn = request.to_request(
        agent_id="sales",
        instance_id="telegram",
        runtime_session_id="chat-42",
        channel_instance=None,
    )

    assert turn.reply_target is target
    assert turn.context["reply_target"] is target


def test_secondary_bridge_qualifies_runtime_session_only() -> None:
    turn = _request().to_request(
        agent_id="sales",
        instance_id="telegram-backup",
        runtime_session_id="telegram-backup:chat-42",
        channel_instance=None,
    )

    assert turn.session_id == "telegram-backup:chat-42"
    assert turn.source.channel_type == "telegram"
    assert turn.context["channel_instance_id"] == "telegram-backup"
    assert turn.reply_target.conversation_id == "chat-42"
