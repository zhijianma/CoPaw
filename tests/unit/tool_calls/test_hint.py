# -*- coding: utf-8 -*-
"""Tests for background tool HintBlock construction."""

from types import SimpleNamespace

from agentscope.message import HintBlock, Msg, TextBlock

from qwenpaw.agents.memory.hint_projection import (
    project_messages_for_memory,
)
from qwenpaw.tool_calls._hint import make_offload_hint_msg


def test_offload_hint_is_hidden_but_memory_equivalent() -> None:
    result = Msg(
        name="tool",
        role="assistant",
        content=[TextBlock(text="result body")],
    )
    entry = SimpleNamespace(
        end_state="completed",
        ctx=SimpleNamespace(tool_name="lookup", tool_call_id="call-1"),
        final_response=result,
    )

    carrier = make_offload_hint_msg(entry)

    assert carrier.role == "assistant"
    assert len(carrier.content) == 1
    assert isinstance(carrier.content[0], HintBlock)
    projected = project_messages_for_memory([carrier])
    assert [block.type for block in projected[0].content] == ["text", "text"]
    assert projected[0].content[1].text == "result body"
    assert isinstance(carrier.content[0], HintBlock)
