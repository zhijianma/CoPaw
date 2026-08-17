# -*- coding: utf-8 -*-
"""Tests for the legacy Channel to core request bridge."""

from qwenpaw.domain.channels.models import (
    AgentBinding,
    ChannelEndpoint,
    ReplyTarget,
)
from qwenpaw.domain.channels.routing import BindingRouter
from qwenpaw.runtime.channel_request_bridge import ChannelRequestBridge
from qwenpaw.schemas import AgentRequest, Message, Role, TextContent


def _request() -> AgentRequest:
    request = AgentRequest(
        session_id="telegram:chat-42",
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


def test_bridge_builds_routed_transport_neutral_request() -> None:
    endpoint = ChannelEndpoint(
        endpoint_id="telegram:sales",
        channel_key="telegram",
        account_id="sales",
    )
    binding = AgentBinding(
        binding_id="telegram:sales->sales",
        endpoint_id=endpoint.endpoint_id,
        agent_id="sales",
    )
    bridge = ChannelRequestBridge(
        endpoint.endpoint_id,
        BindingRouter([endpoint], [binding]),
    )

    turn = bridge.build(_request())

    assert turn.turn_id == "message-9"
    assert turn.agent_id == "sales"
    assert turn.session_id == "telegram:chat-42"
    assert turn.user_id == "user-7"
    assert turn.source.endpoint_id == endpoint.endpoint_id
    assert turn.source.binding_id == binding.binding_id
    assert turn.context["tenant"] == "acme"
    assert isinstance(turn.reply_target, ReplyTarget)
    assert turn.reply_target.conversation_id == "chat-42"
    assert turn.reply_target.thread_id == "thread-3"
    assert turn.messages[0].content[0].text == "hello"


def test_bridge_preserves_an_explicit_reply_target() -> None:
    endpoint = ChannelEndpoint(
        endpoint_id="telegram:sales",
        channel_key="telegram",
        account_id="sales",
    )
    binding = AgentBinding(
        binding_id="telegram:sales->sales",
        endpoint_id=endpoint.endpoint_id,
        agent_id="sales",
    )
    bridge = ChannelRequestBridge(
        endpoint.endpoint_id,
        BindingRouter([endpoint], [binding]),
    )
    request = _request()
    target = ReplyTarget(
        endpoint_id=endpoint.endpoint_id,
        conversation_id="override",
    )
    request.channel_meta["reply_target"] = target
    request.channel_meta["conversation_id"] = "override"

    turn = bridge.build(request)

    assert turn.reply_target is target
    assert turn.context["reply_target"] is target
