# -*- coding: utf-8 -*-
"""Contracts for transport-neutral channel and routing models."""

from __future__ import annotations

import pytest

from qwenpaw.domain.channels.models import (
    AgentBinding,
    ChannelEndpoint,
    InboundMessage,
    ReplyTarget,
)
from qwenpaw.domain.channels.routing import BindingRouter
from qwenpaw.domain.channels.routing import build_turn_request


def test_inbound_message_copies_content_and_metadata() -> None:
    content = ["hello"]
    metadata = {"thread_id": "thread-1"}
    message = InboundMessage(
        message_id="message-1",
        endpoint_id="telegram:primary",
        sender_id="user-1",
        conversation_id="chat-1",
        content=content,
        reply_target=ReplyTarget(
            endpoint_id="telegram:primary",
            conversation_id="chat-1",
        ),
        metadata=metadata,
    )

    content.append("changed")
    metadata["thread_id"] = "changed"

    assert message.content == ("hello",)
    assert message.metadata["thread_id"] == "thread-1"


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("message_id", ""),
        ("endpoint_id", ""),
        ("sender_id", ""),
        ("conversation_id", ""),
    ),
)
def test_inbound_message_requires_routing_identity(
    field: str,
    value: str,
) -> None:
    values = {
        "message_id": "message-1",
        "endpoint_id": "telegram:primary",
        "sender_id": "user-1",
        "conversation_id": "chat-1",
        field: value,
    }

    with pytest.raises(ValueError, match=field):
        InboundMessage(**values)


def test_binding_router_resolves_one_enabled_agent() -> None:
    endpoint = ChannelEndpoint(
        endpoint_id="telegram:primary",
        channel_key="telegram",
        account_id="primary",
    )
    binding = AgentBinding(
        binding_id="binding-1",
        endpoint_id=endpoint.endpoint_id,
        agent_id="sales",
    )
    router = BindingRouter([endpoint], [binding])

    route = router.resolve(
        endpoint.endpoint_id,
        conversation_id="chat-1",
    )

    assert route.binding_id == "binding-1"
    assert route.agent_id == "sales"
    assert route.conversation_id == "chat-1"


def test_binding_router_requires_agent_hint_for_ambiguous_endpoint() -> None:
    endpoint = ChannelEndpoint(
        endpoint_id="slack:workspace-1",
        channel_key="slack",
        account_id="workspace-1",
    )
    bindings = [
        AgentBinding("binding-sales", endpoint.endpoint_id, "sales"),
        AgentBinding("binding-support", endpoint.endpoint_id, "support"),
    ]
    router = BindingRouter([endpoint], bindings)

    with pytest.raises(ValueError, match="Ambiguous endpoint"):
        router.resolve(endpoint.endpoint_id, conversation_id="channel-1")

    route = router.resolve(
        endpoint.endpoint_id,
        conversation_id="channel-1",
        agent_hint="support",
    )
    assert route.agent_id == "support"


def test_binding_router_rejects_disabled_endpoint() -> None:
    endpoint = ChannelEndpoint(
        endpoint_id="discord:primary",
        channel_key="discord",
        account_id="primary",
        enabled=False,
    )
    router = BindingRouter(
        [endpoint],
        [AgentBinding("binding-1", endpoint.endpoint_id, "default")],
    )

    with pytest.raises(LookupError, match="disabled"):
        router.resolve(endpoint.endpoint_id, conversation_id="dm-1")


def test_build_turn_request_preserves_route_and_reply_target() -> None:
    target = ReplyTarget("telegram:primary", "chat-1")
    inbound = InboundMessage(
        message_id="message-1",
        endpoint_id="telegram:primary",
        sender_id="user-1",
        conversation_id="chat-1",
        content=["hello"],
        reply_target=target,
        metadata={"locale": "zh-CN"},
    )
    route = BindingRouter(
        [ChannelEndpoint("telegram:primary", "telegram", "primary")],
        [AgentBinding("binding-1", "telegram:primary", "sales")],
    ).resolve("telegram:primary", conversation_id="chat-1")

    request = build_turn_request(inbound, route, turn_id="turn-1")

    assert request.agent_id == "sales"
    assert request.session_id == "telegram:primary:chat-1"
    assert request.messages == ("hello",)
    assert request.reply_target is target
    assert request.source.endpoint_id == "telegram:primary"
    assert request.source.binding_id == "binding-1"
    assert request.context["locale"] == "zh-CN"
