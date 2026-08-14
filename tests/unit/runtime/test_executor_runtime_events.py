# -*- coding: utf-8 -*-
"""AgentExecutor must expose runtime events, not Console envelopes."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from qwenpaw.domain.turns.events import RuntimeEventType
from qwenpaw.runtime.executor import AgentExecutor


class _Agent:
    def __init__(self, events: list[Any]) -> None:
        self._events = events

    async def reply_stream(self, *, inputs: list[Any]) -> AsyncIterator[Any]:
        del inputs
        for event in self._events:
            yield event


@pytest.mark.asyncio
async def test_executor_yields_transport_neutral_agent_events() -> None:
    first = object()
    second = object()
    executor = AgentExecutor(_Agent([first, second]))

    events = [event async for event in executor.run(["input"])]

    assert [event.type for event in events] == [
        RuntimeEventType.AGENT_EVENT,
        RuntimeEventType.AGENT_EVENT,
    ]
    assert [event.payload for event in events] == [first, second]


def test_executor_module_has_no_envelope_dependency() -> None:
    source = Path("src/qwenpaw/runtime/executor.py").read_text(
        encoding="utf-8",
    )

    assert "from .envelope import" not in source
    assert "Envelope" not in source
