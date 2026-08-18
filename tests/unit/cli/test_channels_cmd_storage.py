# -*- coding: utf-8 -*-
"""Tests for the Catalog-driven Channel CLI editor state."""

from qwenpaw.cli import channels_cmd
from qwenpaw.config.config import AgentProfileConfig, Config


def _agent_with_two_feishu_instances() -> AgentProfileConfig:
    return AgentProfileConfig(
        id="sales",
        name="Sales",
        channels={
            "feishu": {
                "type": "feishu",
                "name": "Main",
                "settings": {"app_id": "main"},
            },
            "feishu-secondary": {
                "type": "feishu",
                "name": "Secondary",
                "settings": {"app_id": "secondary"},
            },
        },
    )


def test_cli_loads_every_channel_instance_and_console() -> None:
    agent = _agent_with_two_feishu_instances()

    state = channels_cmd.load_editable_channel_configs(
        Config(),
        agent,
        "sales",
    )

    assert state.console.enabled is True
    assert [item.instance_id for item in state.channels] == [
        "feishu",
        "feishu-secondary",
    ]
    assert state.channels[1].settings["app_id"] == "secondary"


def test_cli_persists_updates_by_instance_id(monkeypatch) -> None:
    agent = _agent_with_two_feishu_instances()
    state = channels_cmd.load_editable_channel_configs(
        Config(),
        agent,
        "sales",
    )
    state.console.enabled = False
    state.channels[1].name = "Backup"
    state.channels[1].settings["app_id"] = "updated-secondary"
    saved = []
    monkeypatch.setattr(
        channels_cmd,
        "save_agent_config",
        lambda agent_id, value: saved.append((agent_id, value)),
    )

    channels_cmd.persist_editable_channel_configs(
        Config(),
        agent,
        "sales",
        state,
    )

    assert agent.transports.console.enabled is False
    assert agent.channels["feishu"].settings["app_id"] == "main"
    secondary = agent.channels["feishu-secondary"]
    assert secondary.name == "Backup"
    assert secondary.settings["app_id"] == "updated-secondary"
    assert saved == [("sales", agent)]


def test_cli_creates_and_deletes_instances(monkeypatch) -> None:
    agent = _agent_with_two_feishu_instances()
    state = channels_cmd.load_editable_channel_configs(
        Config(),
        agent,
        "sales",
    )
    state.deleted_instance_ids.add("feishu-secondary")
    state.channels = [
        item
        for item in state.channels
        if item.instance_id != "feishu-secondary"
    ]
    state.channels.append(
        channels_cmd.EditableChannel(
            instance_id=None,
            channel_type="feishu",
            name="New Secondary",
            enabled=True,
            settings={"app_id": "new-secondary"},
        ),
    )
    monkeypatch.setattr(channels_cmd, "save_agent_config", lambda *_: None)

    channels_cmd.persist_editable_channel_configs(
        Config(),
        agent,
        "sales",
        state,
    )

    assert "feishu-secondary" not in agent.channels
    new_ids = [
        instance_id
        for instance_id in agent.channels
        if instance_id != "feishu"
    ]
    assert len(new_ids) == 1
    assert new_ids[0].startswith("feishu-")
    assert agent.channels[new_ids[0]].name == "New Secondary"
