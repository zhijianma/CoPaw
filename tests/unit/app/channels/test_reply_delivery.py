# -*- coding: utf-8 -*-
"""Tests for legacy event projection and Channel delivery strategy."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from qwenpaw.app.channels.reply_delivery import ChannelReplyDelivery
from qwenpaw.domain.channels.models import ReplyTarget
from qwenpaw.domain.channels.ports import ReplyEventType
from qwenpaw.runtime.legacy_reply_adapter import LegacyReplyAdapter
from qwenpaw.schemas import RunStatus


def _target() -> ReplyTarget:
    return ReplyTarget(
        endpoint_id="telegram:sales",
        conversation_id="chat-1",
    )


def test_legacy_reply_adapter_classifies_events() -> None:
    adapter = LegacyReplyAdapter("turn-1", _target())

    content = adapter.project(SimpleNamespace(object="content"))
    message = adapter.project(
        SimpleNamespace(
            object="message",
            status=RunStatus.Completed,
        ),
    )
    response = adapter.project(
        SimpleNamespace(object="response", error=None),
    )

    assert content.type == ReplyEventType.CONTENT
    assert message.type == ReplyEventType.MESSAGE
    assert response.type == ReplyEventType.COMPLETED


@pytest.mark.asyncio
async def test_channel_delivery_dispatches_without_runtime_knowledge() -> None:
    channel = SimpleNamespace(
        on_event_content=AsyncMock(return_value=False),
        on_event_message_completed=AsyncMock(),
        on_event_response=AsyncMock(),
        _get_response_error_message=AsyncMock(return_value=None),
    )
    request = SimpleNamespace()
    delivery = ChannelReplyDelivery(
        channel=channel,
        request=request,
        to_handle="chat-1",
        send_meta={"thread_id": "thread-2"},
    )
    adapter = LegacyReplyAdapter("turn-1", _target())
    event = SimpleNamespace(
        object="message",
        status=RunStatus.Completed,
    )

    await delivery.deliver(adapter.project(event))

    channel.on_event_message_completed.assert_awaited_once_with(
        request,
        "chat-1",
        event,
        {"thread_id": "thread-2"},
    )
