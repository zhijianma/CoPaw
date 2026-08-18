# -*- coding: utf-8 -*-
"""Runtime event to outbound reply projection contracts."""

from qwenpaw.domain.channels.models import ReplyTarget
from qwenpaw.domain.channels.ports import ReplyEventType
from qwenpaw.domain.turns.events import RuntimeEvent, RuntimeEventType
from qwenpaw.runtime.reply_projector import ReplyProjector


def test_projector_maps_all_runtime_event_categories() -> None:
    target = ReplyTarget("telegram:primary", "chat-1")
    projector = ReplyProjector(target)
    content = RuntimeEvent.canonical(
        RuntimeEventType.CONTENT_DELTA,
        turn_id="turn-1",
        data={"content_kind": "text", "delta": "hello"},
    )

    projected = [
        projector.project(event)
        for event in (
            RuntimeEvent.turn_started(turn_id="turn-1"),
            content,
            RuntimeEvent.heartbeat(turn_id="turn-1"),
            RuntimeEvent.message("done", turn_id="turn-1"),
            RuntimeEvent.turn_completed(turn_id="turn-1"),
            RuntimeEvent.turn_failed("broken", turn_id="turn-1"),
            RuntimeEvent.turn_cancelled(turn_id="turn-1"),
        )
    ]

    assert [event.type for event in projected] == [
        ReplyEventType.STARTED,
        ReplyEventType.CONTENT,
        ReplyEventType.HEARTBEAT,
        ReplyEventType.MESSAGE,
        ReplyEventType.COMPLETED,
        ReplyEventType.FAILED,
        ReplyEventType.CANCELLED,
    ]
    assert all(event.target is target for event in projected)
    assert projected[1].payload is content
