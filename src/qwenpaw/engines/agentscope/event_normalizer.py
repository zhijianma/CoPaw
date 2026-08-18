# -*- coding: utf-8 -*-
"""Normalize AgentScope events at the engine boundary exactly once."""

from __future__ import annotations

from typing import Any

from agentscope.event import EventType

from ...domain.turns.events import RuntimeEvent, RuntimeEventType

_DIRECT_TYPES = {
    EventType.REPLY_START: RuntimeEventType.REPLY_STARTED,
    EventType.REPLY_END: RuntimeEventType.REPLY_COMPLETED,
    EventType.MODEL_CALL_START: RuntimeEventType.MODEL_CALL_STARTED,
    EventType.MODEL_CALL_END: RuntimeEventType.MODEL_CALL_COMPLETED,
    EventType.TOOL_CALL_START: RuntimeEventType.TOOL_CALL_STARTED,
    EventType.TOOL_CALL_DELTA: RuntimeEventType.TOOL_CALL_DELTA,
    EventType.TOOL_CALL_END: RuntimeEventType.TOOL_CALL_COMPLETED,
    EventType.TOOL_RESULT_START: RuntimeEventType.TOOL_RESULT_STARTED,
    EventType.TOOL_RESULT_END: RuntimeEventType.TOOL_RESULT_COMPLETED,
    EventType.EXCEED_MAX_ITERS: RuntimeEventType.LIMIT_REACHED,
    EventType.CUSTOM: RuntimeEventType.CUSTOM,
}

_CONTENT_TYPES = {
    EventType.TEXT_BLOCK_START: (RuntimeEventType.CONTENT_STARTED, "text"),
    EventType.TEXT_BLOCK_DELTA: (RuntimeEventType.CONTENT_DELTA, "text"),
    EventType.TEXT_BLOCK_END: (RuntimeEventType.CONTENT_COMPLETED, "text"),
    EventType.THINKING_BLOCK_START: (
        RuntimeEventType.CONTENT_STARTED,
        "reasoning",
    ),
    EventType.THINKING_BLOCK_DELTA: (
        RuntimeEventType.CONTENT_DELTA,
        "reasoning",
    ),
    EventType.THINKING_BLOCK_END: (
        RuntimeEventType.CONTENT_COMPLETED,
        "reasoning",
    ),
    EventType.DATA_BLOCK_START: (RuntimeEventType.CONTENT_STARTED, "data"),
    EventType.DATA_BLOCK_DELTA: (RuntimeEventType.CONTENT_DELTA, "data"),
    EventType.DATA_BLOCK_END: (RuntimeEventType.CONTENT_COMPLETED, "data"),
    EventType.HINT_BLOCK: (RuntimeEventType.CONTENT_COMPLETED, "hint"),
}

_TOOL_RESULT_DELTAS = {
    EventType.TOOL_RESULT_TEXT_DELTA: "text",
    EventType.TOOL_RESULT_DATA_DELTA: "data",
}

_INTERACTION_TYPES = {
    EventType.REQUIRE_USER_CONFIRM: (
        RuntimeEventType.INTERACTION_REQUIRED,
        "user_confirmation",
    ),
    EventType.REQUIRE_EXTERNAL_EXECUTION: (
        RuntimeEventType.INTERACTION_REQUIRED,
        "external_execution",
    ),
    EventType.USER_CONFIRM_RESULT: (
        RuntimeEventType.INTERACTION_RESULT,
        "user_confirmation",
    ),
    EventType.USER_INTERRUPT: (
        RuntimeEventType.INTERACTION_RESULT,
        "user_interrupt",
    ),
    EventType.EXTERNAL_EXECUTION_RESULT: (
        RuntimeEventType.INTERACTION_RESULT,
        "external_execution",
    ),
}


class AgentScopeEventNormalizer:
    """Translate native event classes into stable QwenPaw semantics."""

    @staticmethod
    def supported_event_types() -> set[EventType]:
        """Return the complete native event surface owned by this adapter."""
        return (
            set(_DIRECT_TYPES)
            | set(_CONTENT_TYPES)
            | set(_TOOL_RESULT_DELTAS)
            | set(_INTERACTION_TYPES)
        )

    def normalize(self, native: Any, *, turn_id: str = "") -> RuntimeEvent:
        """Normalize one event without retaining the native object."""
        native_type = getattr(native, "type", None)
        try:
            event_type = EventType(native_type)
        except ValueError as error:
            raise ValueError(
                f"Unsupported AgentScope event: {native_type}"
            ) from error

        data = native.model_dump(mode="json")
        metadata = data.pop("metadata", {}) or {}
        data.pop("id", None)
        data.pop("created_at", None)
        data.pop("type", None)

        if "tool_call_name" in data:
            data["name"] = data.pop("tool_call_name")

        if event_type in _CONTENT_TYPES:
            runtime_type, content_kind = _CONTENT_TYPES[event_type]
            data["content_kind"] = content_kind
        elif event_type in _TOOL_RESULT_DELTAS:
            runtime_type = RuntimeEventType.TOOL_RESULT_DELTA
            data["content_kind"] = _TOOL_RESULT_DELTAS[event_type]
        elif event_type in _INTERACTION_TYPES:
            runtime_type, interaction_kind = _INTERACTION_TYPES[event_type]
            data["interaction_kind"] = interaction_kind
        else:
            try:
                runtime_type = _DIRECT_TYPES[event_type]
            except KeyError as error:
                raise ValueError(
                    f"Unsupported AgentScope event: {event_type.value}",
                ) from error

        return RuntimeEvent.canonical(
            runtime_type,
            turn_id=turn_id,
            data=data,
            metadata=metadata,
        )


__all__ = ["AgentScopeEventNormalizer"]
