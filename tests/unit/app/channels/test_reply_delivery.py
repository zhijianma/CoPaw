# -*- coding: utf-8 -*-
"""Tests for canonical Channel event projection and delivery."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from qwenpaw.app.channels.reply_delivery import ChannelReplyDelivery
from qwenpaw.app.channels.event_projector import ChannelEventProjector
from qwenpaw.app.channels.base import BaseChannel
from qwenpaw.domain.channels.models import ReplyTarget
from qwenpaw.domain.channels.ports import ReplyEventType
from qwenpaw.domain.turns.events import RuntimeEvent, RuntimeEventType
from qwenpaw.schemas import RunStatus


def _target() -> ReplyTarget:
    return ReplyTarget(
        channel_type="telegram",
        conversation_id="chat-1",
    )


def test_workspace_injects_runtime_port_without_replacing_plugin_process() -> None:
    legacy_process = object()

    async def runtime_process(_request):
        yield None

    channel = object.__new__(BaseChannel)
    channel._process = legacy_process
    channel._runtime_process = legacy_process
    workspace = SimpleNamespace(stream_channel_events=runtime_process)

    channel.set_workspace(workspace)

    assert channel._process is legacy_process
    assert channel._runtime_process is runtime_process


@pytest.mark.asyncio
async def test_channel_projector_converts_canonical_runtime_event() -> None:
    adapter = ChannelEventProjector(_target())
    event = RuntimeEvent.canonical(
        RuntimeEventType.CONTENT_DELTA,
        turn_id="turn-1",
        data={
            "reply_id": "reply-1",
            "block_id": "text-1",
            "content_kind": "text",
            "delta": "hello",
        },
    )

    presented = list(adapter.project(event))

    assert [reply.type for reply in presented] == [
        ReplyEventType.MESSAGE,
        ReplyEventType.CONTENT,
    ]
    assert presented[1].payload.text == "hello"


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
    event = RuntimeEvent.message(
        SimpleNamespace(get_text_content=lambda: "hello"),
        turn_id="turn-1",
    )
    projected = list(ChannelEventProjector(_target()).project(event))[0]

    await delivery.deliver(projected)

    channel.on_event_message_completed.assert_awaited_once_with(
        request,
        "chat-1",
        projected.payload,
        {"thread_id": "thread-2"},
    )
