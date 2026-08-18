# -*- coding: utf-8 -*-
"""Migration gates for Channel and Runtime protocol boundaries."""

# pylint: disable=protected-access

from __future__ import annotations

import inspect
import re
from pathlib import Path

from qwenpaw.app.channels.base import BaseChannel
from qwenpaw.domain.channels.catalog import BUILTIN_CHANNEL_KEYS
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


def test_console_sse_implementation_is_not_owned_by_base_channel() -> None:
    source = inspect.getsource(BaseChannel)

    assert "ConsoleSseEncoder" not in source

    for forbidden_definition in (
        "def _sanitize_surrogate_text",
        "def _sanitize_for_json",
        "def _strip_event_headlines",
        "def _serialize_event_for_sse",
        "def _flush_headline_stream_states",
    ):
        assert forbidden_definition not in source


def test_console_envelope_is_not_implemented_in_runtime_package() -> None:
    assert not Path("src/qwenpaw/runtime/envelope.py").exists()


def test_channel_identity_map_is_not_redeclared() -> None:
    source = Path("src/qwenpaw/app/channels/conflict.py").read_text(
        encoding="utf-8",
    )

    assert "_CHANNEL_IDENTITY_FIELDS" not in source


def test_legacy_unused_channel_protocol_is_removed() -> None:
    source = Path("src/qwenpaw/app/channels/schema.py").read_text(
        encoding="utf-8",
    )

    assert "class ChannelAddress" not in source
    assert "class ChannelMessageConverter" not in source


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


def test_base_channel_uses_delivery_port_for_common_reply_loops() -> None:
    direct_source = inspect.getsource(BaseChannel._run_process_loop)
    tracker_source = inspect.getsource(BaseChannel._stream_with_tracker)

    assert "ChannelReplyDelivery" not in direct_source
    assert "_create_reply_delivery" in direct_source
    assert "_create_reply_delivery" in tracker_source
    assert "on_event_message_completed" not in direct_source
    assert "on_event_message_completed" not in tracker_source


def test_frontend_mcp_channel_values_match_canonical_catalog() -> None:
    source = Path(
        "console/src/pages/Agent/MCP/accessPolicy.ts",
    ).read_text(encoding="utf-8")
    match = re.search(
        r"MCP_CHANNEL_SOURCE_VALUES\s*=\s*\[(.*?)\]\s*as const",
        source,
        re.DOTALL,
    )

    assert match is not None
    frontend_keys = set(re.findall(r'"([a-z0-9_]+)"', match.group(1)))
    assert frontend_keys == set(BUILTIN_CHANNEL_KEYS)
