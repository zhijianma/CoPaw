# -*- coding: utf-8 -*-
"""TaskTracker stores domain events without transport serialization."""

import asyncio

import pytest

from qwenpaw.app.task_tracker import ReplayBoundary, TaskTracker
from qwenpaw.domain.turns.events import RuntimeEvent


@pytest.mark.asyncio
async def test_reconnect_replays_the_same_runtime_event_object() -> None:
    tracker = TaskTracker()
    produced = asyncio.Event()
    release = asyncio.Event()
    event = RuntimeEvent.turn_started(turn_id="turn-1")

    async def producer(_payload):
        yield event
        produced.set()
        await release.wait()

    original, is_new = await tracker.attach_or_start(
        "chat-1",
        None,
        producer,
    )
    assert is_new is True
    assert await original.get() is event
    await produced.wait()

    reconnect = await tracker.attach("chat-1")
    assert reconnect is not None
    assert await reconnect.get() is event
    assert isinstance(await reconnect.get(), ReplayBoundary)

    release.set()
    async for _ in tracker.stream_from_queue(original, "chat-1"):
        pass
