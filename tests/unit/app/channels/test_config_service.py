# -*- coding: utf-8 -*-
"""Tests for one Channel configuration per type and Agent."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from qwenpaw.app.channels.config_service import ChannelConfigService
from qwenpaw.config.config import AgentProfileConfig


def _agent() -> AgentProfileConfig:
    return AgentProfileConfig(id="sales", name="Sales")


def test_create_rejects_a_second_configuration_of_same_type() -> None:
    service = ChannelConfigService(_agent())
    service.create(
        "telegram",
        {"name": "Main", "settings": {"bot_token": "main"}},
    )

    with pytest.raises(ValueError, match="already configured"):
        service.create(
            "telegram",
            {"name": "Backup", "settings": {"bot_token": "backup"}},
        )


def test_update_and_delete_address_channel_type() -> None:
    agent = _agent()
    service = ChannelConfigService(agent)
    service.create(
        "telegram",
        {"name": "Main", "settings": {"bot_token": "old"}},
    )

    updated = service.update(
        "telegram",
        {
            "name": "Renamed",
            "enabled": False,
            "settings": {"bot_token": "new"},
        },
    )
    removed = service.delete("telegram")

    assert updated.name == "Renamed"
    assert updated.enabled is False
    assert removed.settings["bot_token"] == "new"
    assert agent.channels == {}


def test_invalid_builtin_settings_are_rejected() -> None:
    with pytest.raises(ValidationError):
        ChannelConfigService(_agent()).create(
            "telegram",
            {
                "name": "Main",
                "settings": {"tool_call_max_length": -1},
            },
        )
