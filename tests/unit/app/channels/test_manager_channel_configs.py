# -*- coding: utf-8 -*-
"""Tests for ChannelManager construction from type-keyed configurations."""

# pylint: disable=protected-access

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from qwenpaw.app.channels import manager as manager_module
from qwenpaw.app.channels.base import BaseChannel
from qwenpaw.app.channels.manager import ChannelManager
from qwenpaw.app.channels.manager import _bind_dispatch_callback
from qwenpaw.config.config import AgentProfileConfig, Config, TelegramConfig
from qwenpaw.domain.channels.identity import ChannelIdentity


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
                "type": "telegram",
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
    manager.channels[0].bind_identity.assert_called_once()
    identity = manager.channels[0].bind_identity.call_args.args[0]
    assert identity.instance_id == "telegram"
    assert identity.is_primary is True


def test_manager_builds_multiple_adapters_for_one_channel_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _agent()
    agent.channels["telegram-backup"] = agent.channels["telegram"].model_copy(
        update={"name": "Backup"},
    )
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

    identities = [
        channel.bind_identity.call_args.args[0] for channel in manager.channels
    ]
    assert [item.instance_id for item in identities] == [
        "telegram",
        "telegram-backup",
    ]


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
                "type": "custom_chat",
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
async def test_restart_preserves_plugin_config_and_agent_route() -> None:
    agent = AgentProfileConfig(
        id="sales",
        name="Sales",
        channels={
            "custom_chat": {
                "type": "custom_chat",
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
    replacement.bind_route.assert_called_once_with("sales")
    assert await manager.get_channel("custom_chat") is replacement


def test_channel_state_path_uses_the_channel_workspace(tmp_path) -> None:
    channel = object.__new__(BaseChannel)
    channel.channel = "telegram"

    path = channel.channel_state_path(tmp_path, "state.json")

    assert path == tmp_path / "state.json"


def test_secondary_channel_state_path_is_isolated(tmp_path) -> None:
    channel = object.__new__(BaseChannel)
    channel.channel = "telegram"
    channel._channel_identity = ChannelIdentity(
        "telegram-backup",
        "telegram",
    )

    path = channel.channel_state_path(tmp_path, "state.json")

    assert path.parent.parent == tmp_path / ".channel_instances"


def test_secondary_dispatch_callback_persists_runtime_identity() -> None:
    callback = MagicMock()
    bound = _bind_dispatch_callback(
        callback,
        ChannelIdentity("telegram-backup", "telegram"),
    )

    assert bound is not None
    bound("telegram", "user", "conversation")

    callback.assert_called_once_with(
        "telegram-backup",
        "user",
        "telegram-backup:conversation",
    )


@pytest.mark.asyncio
async def test_secondary_send_event_restores_platform_session() -> None:
    channel = MagicMock(channel="telegram")
    channel._channel_identity = ChannelIdentity(
        "telegram-backup",
        "telegram",
    )
    channel.send_event = AsyncMock()
    manager = ChannelManager([channel])

    await manager.send_event(
        channel="telegram-backup",
        user_id="user",
        session_id="telegram-backup:conversation",
        event=MagicMock(),
    )

    assert channel.send_event.call_args.kwargs["session_id"] == "conversation"
    assert channel.send_event.call_args.kwargs["meta"]["session_id"] == ("conversation")
