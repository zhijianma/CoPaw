# -*- coding: utf-8 -*-
"""Migration gates for Channel and Runtime protocol boundaries."""

from __future__ import annotations

import inspect
import re
from pathlib import Path

from qwenpaw.runtime.runtime import Runtime


_LEGACY_CHANNEL_PROTOCOL_FILES = {
    "base.py",
    "console/channel.py",
    "dingtalk/channel.py",
    "discord_/channel.py",
    "feishu/channel.py",
    "imessage/channel.py",
    "manager.py",
    "matrix/channel.py",
    "mattermost/channel.py",
    "onebot/channel.py",
    "qq/channel.py",
    "schema.py",
    "sip/__init__.py",
    "slack/channel.py",
    "telegram/channel.py",
    "voice/channel.py",
    "voice/conversation_relay.py",
    "wechat/channel.py",
    "wecom/channel.py",
    "xiaoyi/channel.py",
    "yuanbao/channel.py",
}


def test_runtime_event_stream_is_transport_neutral() -> None:
    source = inspect.getsource(Runtime.stream_events)

    for forbidden in (
        "AgentResponse",
        "ConsoleEventPresenter",
        "Envelope",
        "SSE",
    ):
        assert forbidden not in source


def test_legacy_channel_protocol_dependency_does_not_expand() -> None:
    channel_root = Path("src/qwenpaw/app/channels")
    pattern = re.compile(r"\b(?:AgentRequest|AgentResponse)\b")
    current = {
        path.relative_to(channel_root).as_posix()
        for path in channel_root.rglob("*.py")
        if pattern.search(path.read_text(encoding="utf-8"))
    }

    added = current - _LEGACY_CHANNEL_PROTOCOL_FILES
    assert not added, (
        "New Channel files must use transport-neutral messaging models: "
        f"{sorted(added)}"
    )
