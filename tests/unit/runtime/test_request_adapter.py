# -*- coding: utf-8 -*-
"""TurnRequest compatibility adapter contracts."""

from qwenpaw.domain.channels.models import ReplyTarget
from qwenpaw.domain.turns.models import RequestSource, TurnRequest
from qwenpaw.runtime.request_adapter import to_legacy_agent_request
from qwenpaw.schemas import Message, MessageType, Role, TextContent


def test_turn_request_is_adapted_at_one_runtime_boundary() -> None:
    message = Message(
        type=MessageType.MESSAGE,
        role=Role.USER,
        content=[TextContent(type="text", text="hello")],
    )
    target = ReplyTarget("telegram:primary", "chat-1")
    request = TurnRequest(
        turn_id="turn-1",
        agent_id="sales",
        session_id="session-1",
        user_id="user-1",
        messages=[message],
        source=RequestSource(
            kind="channel",
            endpoint_id="telegram:primary",
            binding_id="binding-1",
        ),
        reply_target=target,
        context={"locale": "zh-CN"},
    )

    legacy = to_legacy_agent_request(request)

    assert legacy.id == "turn-1"
    assert legacy.agent_id == "sales"
    assert legacy.session_id == "session-1"
    assert legacy.user_id == "user-1"
    assert legacy.input == [message]
    assert legacy.channel == "telegram"
    assert legacy.channel_meta["endpoint_id"] == "telegram:primary"
    assert legacy.channel_meta["binding_id"] == "binding-1"
    assert legacy.channel_meta["reply_target"] is target
    assert legacy.request_context == {"locale": "zh-CN"}
