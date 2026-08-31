# -*- coding: utf-8 -*-
"""Tests for private runtime context injections."""

from types import SimpleNamespace

from agentscope.message import HintBlock, Msg, TextBlock

from qwenpaw.agents.memory.hint_projection import (
    project_messages_for_memory,
)
from qwenpaw.runtime.runtime import Runtime


def test_context_injection_uses_ordered_assistant_hint() -> None:
    user = Msg(
        name="user",
        role="user",
        content=[TextBlock(text="hello")],
    )
    ctx = SimpleNamespace(
        input_msgs=[user],
        context_injections=[
            {"content": "later", "priority": 20, "source": "b"},
            {"content": "earlier", "priority": 10, "source": "a"},
        ],
    )

    Runtime._apply_context_injections(ctx)

    carrier = ctx.input_msgs[0]
    assert carrier.role == "assistant"
    assert isinstance(carrier.content[0], HintBlock)
    assert carrier.content[0].hint == "earlier\n\nlater"
    assert project_messages_for_memory(ctx.input_msgs) == [user]
