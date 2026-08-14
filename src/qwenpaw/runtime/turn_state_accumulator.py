# -*- coding: utf-8 -*-
"""Accumulate runtime state needed for cancellation persistence."""

from __future__ import annotations

from typing import Any

from agentscope.event import EventType

from ..domain.turns.events import RuntimeEvent, RuntimeEventType


def _event_type(event: Any) -> str:
    value = getattr(event, "type", "")
    return str(getattr(value, "value", value) or "")


class TurnStateAccumulator:
    """Track partial AgentScope output without Console presentation state."""

    def __init__(self) -> None:
        self._text_blocks: dict[str, str] = {}
        self._reasoning_blocks: dict[str, dict[str, Any]] = {}
        self._tool_outputs: dict[str, str] = {}

    def consume(self, runtime_event: RuntimeEvent) -> None:
        """Consume one runtime event if it wraps an AgentScope event."""
        if runtime_event.type is not RuntimeEventType.AGENT_EVENT:
            return

        event = runtime_event.payload
        event_type = _event_type(event)
        block_id = str(getattr(event, "block_id", "") or "")
        call_id = str(getattr(event, "tool_call_id", "") or "")

        if event_type == EventType.TEXT_BLOCK_START.value:
            self._text_blocks.setdefault(block_id, "")
        elif event_type == EventType.TEXT_BLOCK_DELTA.value:
            self._text_blocks[block_id] = self._text_blocks.get(
                block_id,
                "",
            ) + str(getattr(event, "delta", "") or "")
        elif event_type == EventType.THINKING_BLOCK_START.value:
            self._reasoning_blocks.setdefault(
                block_id,
                {"text": "", "completed": False},
            )
        elif event_type == EventType.THINKING_BLOCK_DELTA.value:
            state = self._reasoning_blocks.setdefault(
                block_id,
                {"text": "", "completed": False},
            )
            state["text"] += str(getattr(event, "delta", "") or "")
        elif event_type == EventType.THINKING_BLOCK_END.value:
            state = self._reasoning_blocks.setdefault(
                block_id,
                {"text": "", "completed": False},
            )
            state["completed"] = True
        elif event_type == EventType.TOOL_CALL_START.value:
            self._text_blocks.clear()
        elif event_type == EventType.TOOL_RESULT_START.value:
            self._tool_outputs.setdefault(call_id, "")
        elif event_type == EventType.TOOL_RESULT_TEXT_DELTA.value:
            self._tool_outputs[call_id] = self._tool_outputs.get(
                call_id,
                "",
            ) + str(getattr(event, "delta", "") or "")

    def collect_partial_blocks(self) -> list[tuple[str, str]]:
        """Return unfinished reasoning and current text blocks."""
        result: list[tuple[str, str]] = []
        for state in self._reasoning_blocks.values():
            text = str(state.get("text", "") or "")
            if text and not state.get("completed", False):
                result.append(("thinking", text))
        for text in self._text_blocks.values():
            if text:
                result.append(("text", text))
        return result

    def collect_tool_output(self) -> dict[str, str]:
        """Return accumulated output for incomplete tool results."""
        return {
            call_id: output
            for call_id, output in self._tool_outputs.items()
            if output
        }


__all__ = ["TurnStateAccumulator"]
