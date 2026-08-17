# -*- coding: utf-8 -*-
"""Tests for the legacy Channel to core request bridge."""

from qwenpaw.domain.channels.models import ReplyTarget
from qwenpaw.runtime.channel_request_bridge import ChannelRequestBridge
from qwenpaw.schemas import AgentRequest, Message, Role, TextContent


def _request() -> AgentRequest:
    request = AgentRequest(
        session_id="chat-42",
        user_id="user-7",
        channel="telegram",
        input=[
            Message(
                role=Role.USER,
                content=[TextContent(text="hello")],
            ),
        ],
    )
    request.id = "message-9"
    request.channel_meta = {
        "conversation_id": "chat-42",
        "thread_id": "thread-3",
        "tenant": "acme",
    }
    return request


def test_bridge_preserves_logical_session_identity() -> None:
    bridge = ChannelRequestBridge("sales", "telegram")

    turn = bridge.build(_request())

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
    bridge = ChannelRequestBridge("sales", "telegram")
    request = _request()
    target = ReplyTarget(
        channel_type="telegram",
        conversation_id="override",
    )
    request.channel_meta["reply_target"] = target
    request.channel_meta["conversation_id"] = "override"

    turn = bridge.build(request)

    assert turn.reply_target is target
    assert turn.context["reply_target"] is target
