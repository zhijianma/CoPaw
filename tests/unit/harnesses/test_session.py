# -*- coding: utf-8 -*-
"""Tests for materialized third-party Agent sessions."""

from pathlib import Path

import pytest
from agentscope.state import AgentState

from qwenpaw.app.chats.session import SafeJSONSession
from qwenpaw.app.chats.utils import agentscope_msg_to_message
from qwenpaw.harnesses.events import HarnessEvent, HarnessEventKind
from qwenpaw.harnesses.session import HarnessSessionBridge
from qwenpaw.protocols.console import ConsoleTurnIngress
from qwenpaw.schemas import (
    AgentRequest,
    AudioContent,
    FileContent,
    ImageContent,
    Message,
    MessageType,
    Role,
    TextContent,
    VideoContent,
)


@pytest.mark.asyncio
async def test_bridge_persists_refreshable_reasoning_and_tools(
    tmp_path: Path,
) -> None:
    session = SafeJSONSession(str(tmp_path))
    bridge = HarnessSessionBridge(session)
    request = AgentRequest(
        session_id="chat-1",
        user_id="user-1",
        input=[
            Message(
                role=Role.USER,
                content=[TextContent(text="Fix it")],
            ),
        ],
    )
    events = [
        HarnessEvent(
            kind=HarnessEventKind.REASONING_DELTA,
            text="Checking",
        ),
        HarnessEvent(
            kind=HarnessEventKind.TOOL_STARTED,
            item_id="tool-1",
            tool_name="shell",
            data={"arguments": {"command": "pytest"}},
        ),
        HarnessEvent(
            kind=HarnessEventKind.TOOL_COMPLETED,
            item_id="tool-1",
            tool_name="shell",
            text="1 passed",
        ),
        HarnessEvent(kind=HarnessEventKind.TEXT_DELTA, text="Done"),
    ]

    await bridge.append_turn(
        request=ConsoleTurnIngress().decode(request),
        events=events,
        backend="codex",
    )

    persisted = await session.get_session_state_dict(
        "chat-1",
        "user-1",
        "console",
    )
    state = AgentState.model_validate(persisted["agent"]["state"])
    restored = agentscope_msg_to_message(list(state.context))

    assert [message.type for message in restored] == [
        MessageType.MESSAGE,
        MessageType.REASONING,
        MessageType.PLUGIN_CALL,
        MessageType.PLUGIN_CALL_OUTPUT,
        MessageType.MESSAGE,
    ]
    assert restored[1].content[0].text == "Checking"
    assert restored[3].content[0].data["output"] == "1 passed"


@pytest.mark.asyncio
async def test_bridge_persists_attachment_only_message(
    tmp_path: Path,
) -> None:
    session = SafeJSONSession(str(tmp_path))
    bridge = HarnessSessionBridge(session)
    image_path = tmp_path / "screen.png"
    file_path = tmp_path / "notes.txt"
    audio_path = tmp_path / "voice.mp3"
    video_path = tmp_path / "demo.mp4"
    request = AgentRequest(
        session_id="chat-1",
        user_id="user-1",
        input=[
            Message(
                role=Role.USER,
                content=[
                    ImageContent(image_url=str(image_path)),
                    FileContent(
                        filename="notes.txt",
                        file_url=str(file_path),
                    ),
                    AudioContent(data=str(audio_path), format="mp3"),
                    VideoContent(video_url=str(video_path)),
                ],
            ),
        ],
    )
    await bridge.append_turn(
        request=ConsoleTurnIngress().decode(request),
        events=[],
        backend="codex",
    )

    persisted = await session.get_session_state_dict(
        "chat-1",
        "user-1",
        "console",
    )
    state = AgentState.model_validate(persisted["agent"]["state"])
    restored = agentscope_msg_to_message(list(state.context))

    assert len(restored) == 1
    assert [content.type for content in restored[0].content] == [
        "image",
        "file",
        "audio",
        "video",
    ]
    assert Path(restored[0].content[0].image_url) == image_path
    assert Path(restored[0].content[1].file_url) == file_path
    assert Path(restored[0].content[2].data) == audio_path
    assert Path(restored[0].content[3].video_url) == video_path
