# -*- coding: utf-8 -*-
"""Tests for provider-neutral third-party agent routing."""

# pylint: disable=protected-access

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import patch

import pytest

from qwenpaw.harnesses.base import HarnessAdapter
from qwenpaw.harnesses.events import (
    HarnessAttachment,
    HarnessAttachmentKind,
    HarnessEvent,
    HarnessEventKind,
    HarnessProvider,
)
from qwenpaw.harnesses.runtime import HarnessRuntime
from qwenpaw.domain.turns.events import RuntimeEventType
from qwenpaw.protocols.console import ConsoleTurnIngress
from qwenpaw.schemas import (
    AgentRequest,
    FileContent,
    ImageContent,
    Message,
    Role,
    TextContent,
)


def _core_request(request: AgentRequest):
    return ConsoleTurnIngress().decode(request)


class FakeAdapter(HarnessAdapter):
    """Emit one deterministic response for envelope assertions."""

    def __init__(self) -> None:
        self.stopped = False
        self.prompt = ""
        self.attachments: list[HarnessAttachment] = []

    async def status(self) -> HarnessProvider:
        return HarnessProvider(
            id="codex",
            name="Codex",
            available=True,
            installed=True,
            authenticated=True,
        )

    async def start_login(self, device_code: bool = False) -> dict:
        return {"device_code": device_code}

    async def logout(self) -> None:
        return None

    async def run_turn(  # pylint: disable=invalid-overridden-method
        self,
        *,
        session_id: str,
        prompt: str,
        cwd: Path,
        settings: dict,
        attachments: list[HarnessAttachment] | None = None,
    ) -> AsyncIterator[HarnessEvent]:
        assert session_id == "chat-1"
        assert cwd.is_absolute()
        self.prompt = prompt
        self.attachments = attachments or []
        yield HarnessEvent(
            kind=HarnessEventKind.TEXT_DELTA,
            text="Fixed",
        )
        yield HarnessEvent(kind=HarnessEventKind.COMPLETED)

    async def stop(self) -> None:
        self.stopped = True


class ToolAdapter(FakeAdapter):
    """Emit interleaved reasoning, tool progress, and assistant text."""

    async def run_turn(  # pylint: disable=invalid-overridden-method
        self,
        *,
        session_id: str,
        prompt: str,
        cwd: Path,
        settings: dict,
        attachments: list[HarnessAttachment] | None = None,
    ) -> AsyncIterator[HarnessEvent]:
        del attachments
        yield HarnessEvent(
            kind=HarnessEventKind.REASONING_DELTA,
            text="Checking",
            item_id="reason-1",
        )
        yield HarnessEvent(
            kind=HarnessEventKind.TOOL_STARTED,
            item_id="tool-1",
            tool_name="shell",
            data={
                "arguments": {"command": "pytest -q"},
                "provider_type": "commandExecution",
            },
        )
        yield HarnessEvent(
            kind=HarnessEventKind.TOOL_PROGRESS,
            item_id="tool-1",
            text="1 passed",
        )
        yield HarnessEvent(
            kind=HarnessEventKind.TOOL_COMPLETED,
            item_id="tool-1",
            tool_name="shell",
            text="1 passed",
            data={
                "arguments": {"command": "pytest -q"},
                "provider_type": "commandExecution",
                "exit_code": 0,
            },
        )
        yield HarnessEvent(
            kind=HarnessEventKind.TEXT_DELTA,
            text="Done",
        )
        yield HarnessEvent(kind=HarnessEventKind.COMPLETED)


class CommandAdapter(FakeAdapter):
    """Record a provider-owned command without starting a normal turn."""

    def __init__(self) -> None:
        super().__init__()
        self.command = ""
        self.reset_session_id = ""

    async def run_command(
        self,
        *,
        session_id: str,
        command: str,
        arguments: str,
        cwd: Path,
        settings: dict,
    ) -> list[HarnessEvent]:
        del session_id, arguments, cwd, settings
        self.command = command
        return [
            HarnessEvent(
                kind=HarnessEventKind.TEXT_DELTA,
                text="Compacted",
            ),
            HarnessEvent(kind=HarnessEventKind.COMPLETED),
        ]

    async def reset_session(self, session_id: str) -> None:
        self.reset_session_id = session_id


@pytest.mark.asyncio
async def test_runtime_recreates_adapter_when_binary_changes(
    tmp_path: Path,
) -> None:
    runtime = HarnessRuntime(tmp_path)

    with patch(
        "qwenpaw.harnesses.runtime.create_adapter",
        side_effect=lambda *_args, **_kwargs: FakeAdapter(),
    ):
        first = await runtime.adapter("codex", {"binary": "/first/codex"})
        reused = await runtime.adapter("codex", {"binary": "/first/codex"})
        second = await runtime.adapter("codex", {"binary": "/second/codex"})

    assert reused is first
    assert second is not first
    assert first.stopped is True


@pytest.mark.asyncio
async def test_runtime_emits_canonical_events(tmp_path: Path) -> None:
    runtime = HarnessRuntime(tmp_path)
    adapter = FakeAdapter()
    runtime._adapters["codex"] = adapter
    request = AgentRequest(
        session_id="chat-1",
        input=[
            Message(
                role=Role.USER,
                content=[TextContent(text="Fix it")],
            ),
        ],
    )

    output = [
        item
        async for item in runtime.stream_events(
            backend="codex",
            request=_core_request(request),
            cwd=tmp_path.resolve(),
        )
    ]

    assert [item.type for item in output] == [
        RuntimeEventType.TURN_STARTED,
        RuntimeEventType.CONTENT_STARTED,
        RuntimeEventType.CONTENT_DELTA,
        RuntimeEventType.CONTENT_COMPLETED,
        RuntimeEventType.TURN_COMPLETED,
    ]
    assert output[2].data["delta"] == "Fixed"
    assert adapter.prompt == "Fix it"
    assert adapter.attachments == []


@pytest.mark.asyncio
async def test_runtime_forwards_dropped_image_and_file(
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "screenshot.png"
    file_path = tmp_path / "requirements.txt"
    adapter = FakeAdapter()
    runtime = HarnessRuntime(tmp_path)
    runtime._adapters["codex"] = adapter
    request = AgentRequest(
        session_id="chat-1",
        input=[
            Message(
                role=Role.USER,
                content=[
                    TextContent(text="Inspect these"),
                    ImageContent(image_url=str(image_path)),
                    FileContent(
                        filename="requirements.txt",
                        file_url=str(file_path),
                    ),
                ],
            ),
        ],
    )

    output = [
        item
        async for item in runtime.stream_events(
            backend="codex",
            request=_core_request(request),
            cwd=tmp_path.resolve(),
        )
    ]

    assert output[-1].type is RuntimeEventType.TURN_COMPLETED
    assert adapter.prompt == "Inspect these"
    assert [item.kind for item in adapter.attachments] == [
        HarnessAttachmentKind.IMAGE,
        HarnessAttachmentKind.FILE,
    ]
    assert [item.path for item in adapter.attachments] == [
        image_path,
        file_path,
    ]
    assert adapter.attachments[1].name == "requirements.txt"


@pytest.mark.asyncio
async def test_runtime_allows_attachment_only_turn(tmp_path: Path) -> None:
    image_path = tmp_path / "screenshot.png"
    adapter = FakeAdapter()
    runtime = HarnessRuntime(tmp_path)
    runtime._adapters["codex"] = adapter
    request = AgentRequest(
        session_id="chat-1",
        input=[
            Message(
                role=Role.USER,
                content=[ImageContent(image_url=str(image_path))],
            ),
        ],
    )

    output = [
        item
        async for item in runtime.stream_events(
            backend="codex",
            request=_core_request(request),
            cwd=tmp_path.resolve(),
        )
    ]

    assert output[-1].type is RuntimeEventType.TURN_COMPLETED
    assert adapter.prompt == ""
    assert adapter.attachments[0].path == image_path


@pytest.mark.asyncio
async def test_runtime_emits_reasoning_and_native_tool_envelopes(
    tmp_path: Path,
) -> None:
    runtime = HarnessRuntime(tmp_path)
    runtime._adapters["codex"] = ToolAdapter()
    request = AgentRequest(
        session_id="chat-1",
        input=[
            Message(
                role=Role.USER,
                content=[TextContent(text="Fix it")],
            ),
        ],
    )

    output = [
        item
        async for item in runtime.stream_events(
            backend="codex",
            request=_core_request(request),
            cwd=tmp_path.resolve(),
        )
    ]
    output_types = [event.type for event in output]
    assert RuntimeEventType.CONTENT_DELTA in output_types
    assert RuntimeEventType.TOOL_CALL_STARTED in output_types
    assert RuntimeEventType.TOOL_CALL_COMPLETED in output_types
    assert RuntimeEventType.TOOL_RESULT_COMPLETED in output_types
    tool_call = next(
        event for event in output if event.type is RuntimeEventType.TOOL_CALL_STARTED
    )
    tool_output = next(
        event
        for event in output
        if event.type is RuntimeEventType.TOOL_RESULT_COMPLETED
    )
    assert tool_call.data["name"] == "shell"
    assert tool_output.data["output"] == "1 passed"
    assert tool_output.data["exit_code"] == 0


@pytest.mark.asyncio
async def test_runtime_routes_declared_provider_command(
    tmp_path: Path,
) -> None:
    runtime = HarnessRuntime(tmp_path)
    adapter = CommandAdapter()
    runtime._adapters["codex"] = adapter
    request = AgentRequest(
        session_id="chat-1",
        input=[
            Message(
                role=Role.USER,
                content=[TextContent(text="/compact")],
            ),
        ],
    )

    output = [
        item
        async for item in runtime.stream_events(
            backend="codex",
            request=_core_request(request),
            cwd=tmp_path.resolve(),
        )
    ]

    assert adapter.command == "compact"
    assert output[-1].type is RuntimeEventType.TURN_COMPLETED
    assert any(event.data.get("delta") == "Compacted" for event in output)


@pytest.mark.asyncio
async def test_runtime_handles_host_clear_for_every_backend(
    tmp_path: Path,
) -> None:
    runtime = HarnessRuntime(tmp_path)
    adapter = CommandAdapter()
    runtime._adapters["codex"] = adapter
    request = AgentRequest(
        session_id="chat-1",
        input=[
            Message(
                role=Role.USER,
                content=[TextContent(text="/clear")],
            ),
        ],
    )

    output = [
        item
        async for item in runtime.stream_events(
            backend="codex",
            request=_core_request(request),
            cwd=tmp_path.resolve(),
        )
    ]

    assert adapter.reset_session_id == "chat-1"
    assert output[-1].type is RuntimeEventType.TURN_COMPLETED
