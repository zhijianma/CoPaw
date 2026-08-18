# -*- coding: utf-8 -*-
"""Tests for QwenPaw envelope to ACP tool-call capture."""

from __future__ import annotations

from qwenpaw.agents.acp.server import _RuntimeEventTracker
from qwenpaw.domain.turns.events import RuntimeEvent, RuntimeEventType


def _tool_call_events() -> list[RuntimeEvent]:
    return [
        RuntimeEvent.canonical(
            RuntimeEventType.TOOL_CALL_STARTED,
            data={"tool_call_id": "call-1", "name": "benchmark__lookup"},
        ),
        RuntimeEvent.canonical(
            RuntimeEventType.TOOL_CALL_DELTA,
            data={
                "tool_call_id": "call-1",
                "delta": '{"query": "documentation"}',
            },
        ),
        RuntimeEvent.canonical(
            RuntimeEventType.TOOL_CALL_COMPLETED,
            data={"tool_call_id": "call-1"},
        ),
    ]


def _tool_result_event(state: str) -> RuntimeEvent:
    return RuntimeEvent.canonical(
        RuntimeEventType.TOOL_RESULT_COMPLETED,
        data={
            "tool_call_id": "call-1",
            "name": "benchmark__lookup",
            "output": '{"answer": "found"}',
            "state": state,
        },
    )


def test_acp_tool_capture_preserves_id_name_arguments_and_output() -> None:
    tracker = _RuntimeEventTracker()

    updates = [
        update
        for event in _tool_call_events()
        for update in tracker.process(event)
    ]
    [start] = updates
    [result] = tracker.process(_tool_result_event("success"))

    assert start.tool_call_id == "call-1"
    assert start.title == "benchmark__lookup"
    assert start.status == "in_progress"
    assert start.raw_input == {"query": "documentation"}
    assert result.tool_call_id == "call-1"
    assert result.status == "completed"
    assert result.raw_output == '{"answer": "found"}'
    assert result.content[0].content.text == '{"answer": "found"}'


def test_acp_tool_capture_marks_unsuccessful_results_failed() -> None:
    tracker = _RuntimeEventTracker()

    for state in ("error", "denied", "interrupted"):
        [result] = tracker.process(_tool_result_event(state))
        assert result.tool_call_id == "call-1"
        assert result.status == "failed"
