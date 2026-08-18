# -*- coding: utf-8 -*-
"""Runtime orchestration must expose transport-neutral events."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from qwenpaw.domain.channels.models import ReplyTarget
from qwenpaw.domain.channels.ports import ReplyEventType
from qwenpaw.domain.turns.events import RuntimeEvent, RuntimeEventType
from qwenpaw.runtime.hooks import HookResult
from qwenpaw.runtime.runtime import Runtime
from qwenpaw.schemas import AgentRequest


class _Hooks:
    def __init__(self) -> None:
        self.phases: list[Any] = []

    async def run(self, phase: Any, ctx: Any) -> HookResult:
        del ctx
        self.phases.append(phase)
        return HookResult()


class _Commands:
    async def dispatch(self, text: str, ctx: Any) -> None:
        del text, ctx
        return None


class _Agent:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class _Builder:
    agent = _Agent()

    def __init__(self, *, app_services: Any) -> None:
        del app_services

    async def build(self, ctx: Any) -> _Agent:
        del ctx
        return self.agent


class _Executor:
    def __init__(self, agent: Any, *, turn_id: str = "") -> None:
        del agent
        self.turn_id = turn_id

    async def run(self, msgs: list[Any]):
        del msgs
        yield RuntimeEvent.canonical(
            RuntimeEventType.CONTENT_DELTA,
            turn_id=self.turn_id,
            data={"content_kind": "text", "delta": "hello"},
        )


@pytest.mark.asyncio
async def test_stream_events_emits_runtime_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hooks = _Hooks()
    workspace = SimpleNamespace(
        agent_id="agent-1",
        workspace_dir=None,
        plugins=SimpleNamespace(
            hook_registry=hooks,
            slash_command_registry=_Commands(),
            modes=[],
        ),
    )
    runtime = Runtime(workspace=workspace, app_services=object())
    monkeypatch.setattr("qwenpaw.runtime.runtime.AgentBuilder", _Builder)
    monkeypatch.setattr("qwenpaw.runtime.runtime.AgentExecutor", _Executor)
    request = AgentRequest(
        session_id="session-1",
        user_id="user-1",
    )
    request.id = "turn-1"

    events = [event async for event in runtime.stream_events(request)]

    assert [event.type for event in events] == [
        RuntimeEventType.TURN_STARTED,
        RuntimeEventType.CONTENT_DELTA,
        RuntimeEventType.TURN_COMPLETED,
    ]
    assert events[1].data["delta"] == "hello"
    assert all(event.turn_id == "turn-1" for event in events)
    assert _Builder.agent.closed is True


@pytest.mark.asyncio
async def test_stream_replies_attaches_adapter_owned_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = Runtime(workspace=object(), app_services=object())
    target = ReplyTarget("telegram:primary", "chat-1")

    async def fake_stream_events(request: Any):
        del request
        yield RuntimeEvent.message("hello", turn_id="turn-1")
        yield RuntimeEvent.turn_completed(turn_id="turn-1")

    monkeypatch.setattr(runtime, "stream_events", fake_stream_events)

    replies = [
        event
        async for event in runtime.stream_replies(object(), target=target)
    ]

    assert [event.type for event in replies] == [
        ReplyEventType.MESSAGE,
        ReplyEventType.COMPLETED,
    ]
    assert all(event.target is target for event in replies)
