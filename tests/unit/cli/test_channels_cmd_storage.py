# -*- coding: utf-8 -*-
"""Tests for CLI persistence of agent-owned Channel configurations."""

from qwenpaw.cli import channels_cmd
from qwenpaw.config.config import AgentProfileConfig, Config, TelegramConfig


def test_cli_persists_channel_and_console(monkeypatch) -> None:
    root = Config()
    agent = AgentProfileConfig(id="sales", name="Sales")
    saved = []

    def save_agent(agent_id, value) -> None:
        saved.append((agent_id, value))

    monkeypatch.setattr(
        channels_cmd,
        "save_agent_config",
        save_agent,
    )
    values = {
        "console": {"enabled": False, "bot_prefix": "[web]"},
        "telegram": TelegramConfig(
            enabled=True,
            bot_token="secret",
        ),
    }

    channels_cmd.persist_editable_channel_configs(
        root,
        agent,
        "sales",
        values,
    )

    assert agent.channels["telegram"].settings["bot_token"] == "secret"
    assert agent.transports.console.enabled is False
    assert agent.transports.console.bot_prefix == "[web]"
    assert saved == [("sales", agent)]


def test_cli_loads_the_channel_configuration() -> None:
    root = Config()
    agent = AgentProfileConfig(
        id="sales",
        name="Sales",
        channels={
            "telegram": {
                "name": "Main",
                "settings": {"bot_token": "main"},
            },
        },
    )

    values = channels_cmd.load_editable_channel_configs(
        root,
        agent,
        "sales",
    )

    assert values["telegram"]["bot_token"] == "main"
    assert len(agent.channels) == 1
