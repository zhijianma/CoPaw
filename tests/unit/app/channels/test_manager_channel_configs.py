# -*- coding: utf-8 -*-
"""Tests for ChannelManager construction from type-keyed configurations."""
# pylint: disable=protected-access

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from qwenpaw.app.channels import manager as manager_module
from qwenpaw.app.channels.base import BaseChannel
from qwenpaw.app.channels.manager import ChannelManager
from qwenpaw.config.config import AgentProfileConfig, Config, TelegramConfig


class _FakeTelegramChannel:
    captured_configs = []

    @classmethod
    def from_config(cls, **kwargs):
        cls.captured_configs.append(kwargs["config"])
        channel = MagicMock()
        channel.channel = "telegram"
        return channel


@pytest.fixture(autouse=True)
def _reset_fake_channel() -> None:
    _FakeTelegramChannel.captured_configs = []


def _agent() -> AgentProfileConfig:
    return AgentProfileConfig(
        id="sales",
        name="Sales",
        channels={
            "telegram": {
                "name": "Sales Bot",
                "settings": {
                    "bot_token": "secret",
                    "tool_call_max_length": 42,
                },
            },
        },
    )


def test_manager_builds_one_adapter_for_channel_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        manager_module,
        "get_available_channels",
        lambda: ["telegram"],
    )
    monkeypatch.setattr(
        manager_module,
        "get_channel_registry",
        lambda **_kwargs: {"telegram": _FakeTelegramChannel},
    )

    manager = ChannelManager.from_config(
        process=MagicMock(),
        config=Config(),
        agent_config=_agent(),
    )

    assert len(manager.channels) == 1
    assert manager.channels[0].channel == "telegram"
    config = _FakeTelegramChannel.captured_configs[0]
    assert isinstance(config, TelegramConfig)
    assert config.bot_token == "secret"


def test_manager_skips_disabled_channel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _agent()
    agent.channels["telegram"].enabled = False
    monkeypatch.setattr(
        manager_module,
        "get_available_channels",
        lambda: ["telegram"],
    )
    monkeypatch.setattr(
        manager_module,
        "get_channel_registry",
        lambda **_kwargs: {"telegram": _FakeTelegramChannel},
    )

    manager = ChannelManager.from_config(
        process=MagicMock(),
        config=Config(),
        agent_config=agent,
    )

    assert manager.channels == []


@pytest.mark.asyncio
async def test_manager_resolves_channel_by_type() -> None:
    channel = MagicMock(channel="telegram")
    manager = ChannelManager([channel])

    assert await manager.get_channel("telegram") is channel


def test_manager_preserves_plugin_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin_channel = MagicMock(channel="custom_chat")
    plugin_class = MagicMock()
    plugin_class.from_config.return_value = plugin_channel
    agent = AgentProfileConfig(
        id="sales",
        name="Sales",
        channels={
            "custom_chat": {
                "name": "Custom",
                "settings": {"server": "https://plugin.invalid"},
            },
        },
    )
    monkeypatch.setattr(
        manager_module,
        "get_available_channels",
        lambda: ["custom_chat"],
    )
    monkeypatch.setattr(
        manager_module,
        "get_channel_registry",
        lambda **_kwargs: {"custom_chat": plugin_class},
    )

    ChannelManager.from_config(
        process=MagicMock(),
        config=Config(),
        agent_config=agent,
    )

    config = plugin_class.from_config.call_args.kwargs["config"]
    assert config.server == "https://plugin.invalid"


@pytest.mark.asyncio
async def test_restart_preserves_plugin_config_and_channel_bridge() -> None:
    agent = AgentProfileConfig(
        id="sales",
        name="Sales",
        channels={
            "custom_chat": {
                "name": "Custom",
                "settings": {"server": "https://plugin.invalid"},
            },
        },
    )
    original = MagicMock(channel="custom_chat")
    original.stop = AsyncMock()
    replacement = MagicMock(channel="custom_chat")
    replacement.start = AsyncMock()
    replacement.stop = AsyncMock()
    original.clone.return_value = replacement
    manager = ChannelManager([original])
    manager._workspace = MagicMock(config=agent)

    await manager.restart_channel("custom_chat")

    plugin_config = original.clone.call_args.args[0]
    assert plugin_config.server == "https://plugin.invalid"
    bridge = replacement.set_request_bridge.call_args.args[0]
    assert bridge._channel_type == "custom_chat"
    assert bridge._agent_id == "sales"
    assert await manager.get_channel("custom_chat") is replacement


def test_channel_state_path_uses_the_channel_workspace(tmp_path) -> None:
    channel = object.__new__(BaseChannel)
    channel.channel = "telegram"

    path = channel.channel_state_path(tmp_path, "state.json")

    assert path == tmp_path / "state.json"
