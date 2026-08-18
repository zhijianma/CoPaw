# -*- coding: utf-8 -*-
"""Tests for agent-owned Channel instances."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from qwenpaw.app.channels.config_service import ChannelConfigService
from qwenpaw.config.config import AgentProfileConfig


def _agent() -> AgentProfileConfig:
    return AgentProfileConfig(id="sales", name="Sales")


def test_create_keeps_primary_id_and_generates_secondary_id() -> None:
    agent = _agent()
    service = ChannelConfigService(agent)
    primary_id, primary = service.create(
        "telegram",
        {"name": "Main", "settings": {"bot_token": "main"}},
    )
    secondary_id, secondary = service.create(
        "telegram",
        {"name": "Backup", "settings": {"bot_token": "backup"}},
    )

    assert primary_id == "telegram"
    assert primary.type == "telegram"
    assert secondary_id.startswith("telegram-")
    assert secondary_id != primary_id
    assert secondary.type == "telegram"
    assert list(agent.channels) == [primary_id, secondary_id]


def test_update_and_delete_address_channel_type() -> None:
    agent = _agent()
    service = ChannelConfigService(agent)
    instance_id, _ = service.create(
        "telegram",
        {"name": "Main", "settings": {"bot_token": "old"}},
    )

    updated = service.update(
        instance_id,
        {
            "name": "Renamed",
            "enabled": False,
            "settings": {"bot_token": "new"},
        },
    )
    removed = service.delete(instance_id)

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


def test_update_rejects_instance_type_changes() -> None:
    service = ChannelConfigService(_agent())
    instance_id, _ = service.create(
        "telegram",
        {"name": "Main", "settings": {}},
    )

    with pytest.raises(ValueError, match="cannot be changed"):
        service.update(
            instance_id,
            {"type": "feishu", "name": "Wrong", "settings": {}},
        )


def test_primary_cannot_be_deleted_while_secondary_exists() -> None:
    agent = _agent()
    service = ChannelConfigService(agent)
    service.create("telegram", {"name": "Main", "settings": {}})
    secondary_id, _ = service.create(
        "telegram",
        {"name": "Backup", "settings": {}},
    )

    with pytest.raises(ValueError, match="primary"):
        service.delete("telegram")

    service.delete(secondary_id)
    service.delete("telegram")
    assert agent.channels == {}
