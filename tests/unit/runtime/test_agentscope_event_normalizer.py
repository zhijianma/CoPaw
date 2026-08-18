# -*- coding: utf-8 -*-
"""AgentScope events cross the core boundary through one normalizer."""

from agentscope.event import (
    EventType,
    TextBlockDeltaEvent,
    ToolCallStartEvent,
)

from qwenpaw.domain.turns.events import RuntimeEventType
from qwenpaw.engines.agentscope.event_normalizer import (
    AgentScopeEventNormalizer,
)


def test_normalizer_emits_canonical_content_event() -> None:
    native = TextBlockDeltaEvent(
        reply_id="reply-1",
        block_id="text-1",
        delta="hello",
    )

    event = AgentScopeEventNormalizer().normalize(native, turn_id="turn-1")

    assert event.type is RuntimeEventType.CONTENT_DELTA
    assert event.turn_id == "turn-1"
    assert event.data == {
        "reply_id": "reply-1",
        "block_id": "text-1",
        "content_kind": "text",
        "delta": "hello",
    }
    assert native not in event.data.values()
    assert EventType.TEXT_BLOCK_DELTA.value not in event.data.values()


def test_normalizer_emits_canonical_tool_event() -> None:
    native = ToolCallStartEvent(
        reply_id="reply-1",
        tool_call_id="call-1",
        tool_call_name="search",
    )

    event = AgentScopeEventNormalizer().normalize(native, turn_id="turn-1")

    assert event.type is RuntimeEventType.TOOL_CALL_STARTED
    assert event.data["tool_call_id"] == "call-1"
    assert event.data["name"] == "search"


def test_normalizer_covers_every_agentscope_event_type() -> None:
    assert AgentScopeEventNormalizer.supported_event_types() == set(EventType)
