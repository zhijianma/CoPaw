# -*- coding: utf-8 -*-
"""Runtime turn state must not depend on the Console Envelope."""

from __future__ import annotations

from typing import Any

from qwenpaw.domain.turns.events import RuntimeEvent, RuntimeEventType
from qwenpaw.runtime.turn_state_accumulator import TurnStateAccumulator


def _event(event_type: RuntimeEventType, **fields: Any) -> RuntimeEvent:
    return RuntimeEvent.canonical(
        event_type,
        data=fields,
    )


def test_accumulator_collects_unfinished_text_and_reasoning() -> None:
    state = TurnStateAccumulator()

    state.consume(
        _event(
            RuntimeEventType.CONTENT_STARTED,
            block_id="thinking",
            content_kind="reasoning",
        ),
    )
    state.consume(
        _event(
            RuntimeEventType.CONTENT_DELTA,
            block_id="thinking",
            content_kind="reasoning",
            delta="plan",
        ),
    )
    state.consume(
        _event(
            RuntimeEventType.CONTENT_STARTED,
            block_id="text",
            content_kind="text",
        ),
    )
    state.consume(
        _event(
            RuntimeEventType.CONTENT_DELTA,
            block_id="text",
            content_kind="text",
            delta="answer",
        ),
    )

    assert state.collect_partial_blocks() == [
        ("thinking", "plan"),
        ("text", "answer"),
    ]


def test_accumulator_excludes_completed_reasoning() -> None:
    state = TurnStateAccumulator()
    state.consume(
        _event(
            RuntimeEventType.CONTENT_STARTED,
            block_id="thinking",
            content_kind="reasoning",
        ),
    )
    state.consume(
        _event(
            RuntimeEventType.CONTENT_DELTA,
            block_id="thinking",
            content_kind="reasoning",
            delta="done",
        ),
    )
    state.consume(
        _event(
            RuntimeEventType.CONTENT_COMPLETED,
            block_id="thinking",
            content_kind="reasoning",
        ),
    )

    assert not state.collect_partial_blocks()


def test_accumulator_collects_partial_tool_output() -> None:
    state = TurnStateAccumulator()
    state.consume(
        _event(
            RuntimeEventType.TOOL_RESULT_STARTED,
            tool_call_id="call-1",
        ),
    )
    state.consume(
        _event(
            RuntimeEventType.TOOL_RESULT_DELTA,
            tool_call_id="call-1",
            content_kind="text",
            delta="first",
        ),
    )
    state.consume(
        _event(
            RuntimeEventType.TOOL_RESULT_DELTA,
            tool_call_id="call-1",
            content_kind="text",
            delta=" second",
        ),
    )

    assert state.collect_tool_output() == {"call-1": "first second"}


def test_non_agent_events_do_not_change_accumulated_state() -> None:
    state = TurnStateAccumulator()

    state.consume(RuntimeEvent.heartbeat())
    state.consume(RuntimeEvent.turn_completed())

    assert not state.collect_partial_blocks()
    assert state.collect_tool_output() == {}
