# -*- coding: utf-8 -*-
"""Runtime turn state must not depend on the Console Envelope."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from agentscope.event import EventType

from qwenpaw.domain.turns.events import RuntimeEvent
from qwenpaw.runtime.turn_state_accumulator import TurnStateAccumulator


def _event(event_type: EventType, **fields: Any) -> RuntimeEvent:
    return RuntimeEvent.agent_event(
        SimpleNamespace(type=event_type.value, **fields),
    )


def test_accumulator_collects_unfinished_text_and_reasoning() -> None:
    state = TurnStateAccumulator()

    state.consume(
        _event(EventType.THINKING_BLOCK_START, block_id="thinking"),
    )
    state.consume(
        _event(
            EventType.THINKING_BLOCK_DELTA,
            block_id="thinking",
            delta="plan",
        ),
    )
    state.consume(_event(EventType.TEXT_BLOCK_START, block_id="text"))
    state.consume(
        _event(
            EventType.TEXT_BLOCK_DELTA,
            block_id="text",
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
        _event(EventType.THINKING_BLOCK_START, block_id="thinking"),
    )
    state.consume(
        _event(
            EventType.THINKING_BLOCK_DELTA,
            block_id="thinking",
            delta="done",
        ),
    )
    state.consume(
        _event(EventType.THINKING_BLOCK_END, block_id="thinking"),
    )

    assert not state.collect_partial_blocks()


def test_accumulator_collects_partial_tool_output() -> None:
    state = TurnStateAccumulator()
    state.consume(
        _event(
            EventType.TOOL_RESULT_START,
            tool_call_id="call-1",
        ),
    )
    state.consume(
        _event(
            EventType.TOOL_RESULT_TEXT_DELTA,
            tool_call_id="call-1",
            delta="first",
        ),
    )
    state.consume(
        _event(
            EventType.TOOL_RESULT_TEXT_DELTA,
            tool_call_id="call-1",
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
