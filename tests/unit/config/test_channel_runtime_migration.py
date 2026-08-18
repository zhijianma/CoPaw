# -*- coding: utf-8 -*-
"""Tests for the one-shot migration from the original Channel map."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from qwenpaw.config import channel_migration
from qwenpaw.config.channel_migration import (
    CHANNEL_RUNTIME_MIGRATION_VERSION,
    ChannelMigrationError,
    channel_configuration_requires_migration,
    migrate_channel_configuration,
)
from qwenpaw.config.config import AgentProfileConfig


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _install(tmp_path: Path) -> tuple[Path, Path]:
    workspace = tmp_path / "workspaces" / "sales"
    agent_path = workspace / "agent.json"
    _write_json(
        agent_path,
        {"id": "sales", "name": "Sales", "channels": {}},
    )
    config_path = tmp_path / "config.json"
    _write_json(
        config_path,
        {
            "agents": {
                "active_agent": "sales",
                "profiles": {
                    "sales": {
                        "id": "sales",
                        "workspace_dir": str(workspace),
                    },
                },
            },
        },
    )
    return config_path, agent_path


def test_migrates_only_original_flat_channel_map(tmp_path: Path) -> None:
    config_path, agent_path = _install(tmp_path)
    agent = _read_json(agent_path)
    agent["channels"] = {
        "console": {"enabled": False, "show_thinking": False},
        "telegram": {
            "enabled": True,
            "bot_token": "secret",
            "filter_tool_messages": True,
        },
        "dingtalk": {
            "enabled": False,
            "client_id": "configured-disabled",
        },
        "discord": {"enabled": False},
    }
    _write_json(agent_path, agent)

    result = migrate_channel_configuration(config_path)

    migrated = _read_json(agent_path)
    assert result.migrated is True
    assert result.migrated_agents == ("sales",)
    assert migrated["channel_schema_version"] == (
        CHANNEL_RUNTIME_MIGRATION_VERSION
    )
    assert migrated["transports"]["console"]["enabled"] is False
    assert list(migrated["channels"]) == ["dingtalk", "telegram"]
    assert migrated["channels"]["telegram"] == {
        "type": "telegram",
        "name": "Telegram",
        "enabled": True,
        "settings": {
            "bot_token": "secret",
            "show_tool_calls": False,
            "show_tool_results": False,
        },
    }
    AgentProfileConfig.model_validate(migrated)


def test_migrates_original_root_channels_to_active_agent(
    tmp_path: Path,
) -> None:
    config_path, agent_path = _install(tmp_path)
    root = _read_json(config_path)
    root["channels"] = {
        "telegram": {"enabled": True, "bot_token": "secret"},
    }
    _write_json(config_path, root)

    result = migrate_channel_configuration(config_path)

    assert result.migrated is True
    assert "channels" not in _read_json(config_path)
    assert _read_json(agent_path)["channels"]["telegram"]["settings"] == {
        "bot_token": "secret",
    }


def test_current_instance_map_is_not_migrated(tmp_path: Path) -> None:
    config_path, agent_path = _install(tmp_path)
    current = _read_json(agent_path)
    current["channels"] = {
        "feishu": {
            "type": "feishu",
            "name": "Primary",
            "enabled": True,
            "settings": {"app_id": "primary"},
        },
        "feishu-2f87b8f4": {
            "type": "feishu",
            "name": "Secondary",
            "enabled": True,
            "settings": {"app_id": "secondary"},
        },
    }
    _write_json(agent_path, current)
    original = agent_path.read_bytes()

    result = migrate_channel_configuration(config_path)

    assert result.migrated is False
    assert agent_path.read_bytes() == original
    assert channel_configuration_requires_migration(current) is False


def test_development_list_format_is_not_migrated(tmp_path: Path) -> None:
    config_path, agent_path = _install(tmp_path)
    agent = _read_json(agent_path)
    agent["channel_schema_version"] = 2
    agent["channels"] = [
        {
            "id": "telegram-main",
            "type": "telegram",
            "name": "Main",
            "settings": {"bot_token": "secret"},
        },
    ]
    _write_json(agent_path, agent)
    original = agent_path.read_bytes()

    with pytest.raises(
        ChannelMigrationError,
        match="unsupported development Channel format",
    ):
        migrate_channel_configuration(config_path)

    assert agent_path.read_bytes() == original
    assert channel_configuration_requires_migration(agent) is False


def test_development_mixed_map_is_not_migrated(tmp_path: Path) -> None:
    config_path, agent_path = _install(tmp_path)
    agent = _read_json(agent_path)
    agent["channels"] = {
        "feishu": {
            "enabled": True,
            "app_id": "original-primary",
        },
        "feishu-secondary": {
            "type": "feishu",
            "name": "Development Secondary",
            "enabled": True,
            "settings": {"app_id": "development-secondary"},
        },
    }
    _write_json(agent_path, agent)
    original = agent_path.read_bytes()

    with pytest.raises(
        ChannelMigrationError,
        match="unsupported mixed Channel format",
    ):
        migrate_channel_configuration(config_path)

    assert agent_path.read_bytes() == original
    assert channel_configuration_requires_migration(agent) is False


def test_channel_routing_is_not_projected_into_agents(
    tmp_path: Path,
) -> None:
    config_path, agent_path = _install(tmp_path)
    root = _read_json(config_path)
    root["channel_routing"] = {
        "endpoints": [
            {
                "endpoint_id": "feishu-dev",
                "channel_key": "feishu",
                "settings": {"app_id": "must-not-be-projected"},
            },
        ],
        "bindings": [
            {"endpoint_id": "feishu-dev", "agent_id": "sales"},
        ],
    }
    _write_json(config_path, root)
    original_root = config_path.read_bytes()
    original_agent = agent_path.read_bytes()

    result = migrate_channel_configuration(config_path)

    assert result.migrated is False
    assert config_path.read_bytes() == original_root
    assert agent_path.read_bytes() == original_agent


def test_migration_is_idempotent(tmp_path: Path) -> None:
    config_path, agent_path = _install(tmp_path)
    agent = _read_json(agent_path)
    agent["channels"] = {
        "onebot": {
            "enabled": False,
            "ws_host": "127.0.0.1",
            "media_download_max_mb": 75,
        },
    }
    _write_json(agent_path, agent)

    first = migrate_channel_configuration(config_path)
    after_first = agent_path.read_bytes()
    second = migrate_channel_configuration(config_path)

    assert first.migrated is True
    assert second.migrated is False
    assert agent_path.read_bytes() == after_first
    settings = _read_json(agent_path)["channels"]["onebot"]["settings"]
    assert settings["media_download_max_mb"] == 75


def test_migration_creates_recoverable_backup_manifest(
    tmp_path: Path,
) -> None:
    config_path, agent_path = _install(tmp_path)
    agent = _read_json(agent_path)
    agent["channels"] = {
        "telegram": {"enabled": True, "bot_token": "secret"},
    }
    _write_json(agent_path, agent)

    result = migrate_channel_configuration(config_path)

    assert result.backup_dir is not None
    manifest = _read_json(result.backup_dir / "manifest.json")
    assert manifest["migration_version"] == (
        CHANNEL_RUNTIME_MIGRATION_VERSION
    )
    assert "workspaces/sales/agent.json" in manifest["files"]


def test_migration_restores_sources_when_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path, agent_path = _install(tmp_path)
    root = _read_json(config_path)
    root["channels"] = {
        "telegram": {"enabled": True, "bot_token": "secret"},
    }
    _write_json(config_path, root)
    original_root = config_path.read_bytes()
    original_agent = agent_path.read_bytes()
    real_write = channel_migration.write_json_atomic
    calls = 0

    def fail_agent_write(path: Path, value: dict) -> None:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError("injected migration failure")
        real_write(path, value)

    monkeypatch.setattr(
        channel_migration,
        "write_json_atomic",
        fail_agent_write,
    )

    with pytest.raises(ChannelMigrationError, match="write failed"):
        migrate_channel_configuration(config_path)

    assert config_path.read_bytes() == original_root
    assert agent_path.read_bytes() == original_agent
