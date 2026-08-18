# -*- coding: utf-8 -*-
"""Tests for workspace routing into a selected third-party agent."""

# pylint: disable=protected-access

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from qwenpaw.app.workspace.workspace import Workspace
from qwenpaw.domain.turns.events import RuntimeEvent
from qwenpaw.domain.turns.models import TurnRequest


class FakeHarnessRuntime:
    """Record the routing inputs received from a workspace."""

    def __init__(self) -> None:
        self.call: dict[str, Any] | None = None

    async def stream_events(self, **kwargs: Any) -> AsyncIterator[RuntimeEvent]:
        self.call = kwargs
        yield RuntimeEvent.turn_completed(turn_id="turn-1")


@pytest.mark.asyncio
async def test_coding_mode_routes_directly_to_harness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = SimpleNamespace(
        backend="codex",
        coding_mode=SimpleNamespace(enabled=False),
    )
    monkeypatch.setattr(
        "qwenpaw.app.workspace.workspace.load_agent_config",
        lambda _agent_id: config,
    )
    workspace = Workspace("agent-1", str(tmp_path / "workspace"))
    runtime = FakeHarnessRuntime()
    workspace._harness_runtime = runtime
    request = object()

    output = [item async for item in workspace.stream_query(request)]

    assert output[-1].object == "response"
    assert output[-1].status == "completed"
    assert runtime.call is not None
    assert runtime.call["backend"] == "codex"
    assert runtime.call["cwd"] == (tmp_path / "workspace").resolve()
    core_request = runtime.call["request"]
    assert isinstance(core_request, TurnRequest)
    assert core_request.agent_id == "agent-1"
    assert runtime.call["settings"]["_request_context"] == {
        "agent_id": "agent-1",
        "session_id": core_request.session_id,
        "user_id": core_request.user_id,
        "channel": "console",
    }
