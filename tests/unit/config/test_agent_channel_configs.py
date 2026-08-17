# -*- coding: utf-8 -*-
"""Tests for one Channel configuration per type and Agent."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from qwenpaw.config.config import AgentProfileConfig, TelegramConfig


def test_agent_owns_one_configuration_per_channel_type() -> None:
    agent = AgentProfileConfig(
        id="sales",
        name="Sales",
        channels={
            "telegram": {
                "name": "Sales Bot",
                "enabled": True,
                "settings": {"bot_token": "token"},
            },
            "feishu": {
                "name": "Sales Feishu",
                "enabled": False,
                "settings": {},
            },
        },
    )

    assert set(agent.channels) == {"feishu", "telegram"}
    assert agent.channels["telegram"].name == "Sales Bot"


def test_builtin_channel_settings_are_typed_and_normalized() -> None:
    agent = AgentProfileConfig(
        id="sales",
        name="Sales",
        channels={
            "telegram": {
                "name": "Main Bot",
                "settings": {"tool_call_max_length": "42"},
            },
        },
    )

    channel = agent.channels["telegram"]
    typed = channel.typed_config("telegram")
    assert isinstance(typed, TelegramConfig)
    assert channel.settings["tool_call_max_length"] == 42


def test_channel_settings_cannot_override_enabled() -> None:
    with pytest.raises(ValidationError, match="enabled belongs to"):
        AgentProfileConfig(
            id="sales",
            name="Sales",
            channels={
                "telegram": {
                    "name": "Main Bot",
                    "settings": {"enabled": False},
                },
            },
        )


def test_console_cannot_be_configured_as_channel() -> None:
    with pytest.raises(ValidationError, match="Console is a Transport"):
        AgentProfileConfig(
            id="sales",
            name="Sales",
            channels={
                "console": {
                    "name": "Console",
                    "settings": {},
                },
            },
        )
