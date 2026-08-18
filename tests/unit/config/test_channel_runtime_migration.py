# -*- coding: utf-8 -*-
"""Tests for persistent migration to agent-owned Channel instances."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pytest

from qwenpaw.config import channel_migration
from qwenpaw.config.channel_migration import (
    CHANNEL_RUNTIME_MIGRATION_VERSION,
    ChannelMigrationError,
    migrate_channel_configuration,
)
from qwenpaw.config.config import AgentProfileConfig
from qwenpaw.app.chats.session import session_filename


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
        {
            "id": "sales",
            "name": "Sales",
            "channels": {},
        },
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


def test_migrates_v2_instance_list_to_instance_keyed_configuration(
    tmp_path: Path,
) -> None:
    config_path, agent_path = _install(tmp_path)
    agent = _read_json(agent_path)
    agent["channel_schema_version"] = 2
    agent["channels"] = [
        {
            "id": "telegram-main",
            "type": "telegram",
            "name": "Main Bot",
            "enabled": True,
            "settings": {"bot_token": "secret"},
        },
    ]
    _write_json(agent_path, agent)

    migrate_channel_configuration(config_path)

    migrated = _read_json(agent_path)
    assert migrated["channel_schema_version"] == 5
    assert migrated["channels"] == {
        "telegram": {
            "type": "telegram",
            "name": "Main Bot",
            "enabled": True,
            "settings": {"bot_token": "secret"},
        },
    }
    AgentProfileConfig.model_validate(migrated)


def test_migration_keeps_multiple_configs_of_same_type(
    tmp_path: Path,
) -> None:
    config_path, agent_path = _install(tmp_path)
    agent = _read_json(agent_path)
    agent["channel_schema_version"] = 2
    agent["channels"] = [
        {
            "id": "telegram-main",
            "type": "telegram",
            "name": "Main",
            "settings": {"bot_token": "main"},
        },
        {
            "id": "telegram-backup",
            "type": "telegram",
            "name": "Backup",
            "settings": {"bot_token": "backup"},
        },
    ]
    _write_json(agent_path, agent)
    migrate_channel_configuration(config_path)

    migrated = _read_json(agent_path)
    assert migrated["channels"] == {
        "telegram": {
            "type": "telegram",
            "name": "Main",
            "enabled": True,
            "settings": {"bot_token": "main"},
        },
        "telegram-backup": {
            "type": "telegram",
            "name": "Backup",
            "enabled": True,
            "settings": {"bot_token": "backup"},
        },
    }


def test_v2_migration_rejects_duplicate_legacy_instance_ids(
    tmp_path: Path,
) -> None:
    config_path, agent_path = _install(tmp_path)
    agent = _read_json(agent_path)
    agent["channel_schema_version"] = 2
    agent["channels"] = [
        {
            "id": "shared-instance",
            "type": "telegram",
            "settings": {"bot_token": "main"},
        },
        {
            "id": "shared-instance",
            "type": "feishu",
            "settings": {},
        },
    ]
    _write_json(agent_path, agent)

    with pytest.raises(
        ChannelMigrationError,
        match="Duplicate Channel instance ID: shared-instance",
    ):
        migrate_channel_configuration(config_path)


def test_v2_secondary_history_gets_an_instance_chat_index(
    tmp_path: Path,
) -> None:
    config_path, agent_path = _install(tmp_path)
    workspace = agent_path.parent
    agent = _read_json(agent_path)
    agent["channel_schema_version"] = 2
    agent["channels"] = [
        {
            "id": "feishu-main",
            "type": "feishu",
            "name": "Main",
            "settings": {},
        },
        {
            "id": "feishu-backup",
            "type": "feishu",
            "name": "Backup",
            "settings": {},
        },
    ]
    _write_json(agent_path, agent)
    _write_json(
        workspace / "chats.json",
        {
            "version": 1,
            "chats": [
                {
                    "id": "legacy-chat",
                    "name": "Feishu",
                    "session_id": "tenant:conversation",
                    "user_id": "ou-user",
                    "channel": "feishu",
                },
            ],
        },
    )
    session_dir = workspace / "sessions" / "feishu"
    primary_path = session_dir / session_filename(
        "feishu-main:tenant:conversation",
        "ou-user",
    )
    secondary_path = session_dir / session_filename(
        "feishu-backup:tenant:conversation",
        "ou-user",
    )
    _write_json(primary_path, {"agent": {"state": {"context": []}}})
    _write_json(secondary_path, {"agent": {"state": {"context": []}}})

    migrate_channel_configuration(config_path)

    chats = _read_json(workspace / "chats.json")["chats"]
    secondary = next(
        chat
        for chat in chats
        if chat["session_id"] == "feishu-backup:tenant:conversation"
    )
    assert secondary["channel"] == "feishu"
    assert secondary["meta"]["channel_instance_id"] == "feishu-backup"
    assert secondary_path.exists()


def test_v4_to_v5_does_not_rewrite_chat_or_session_files(
    tmp_path: Path,
) -> None:
    config_path, agent_path = _install(tmp_path)
    workspace = agent_path.parent
    agent = _read_json(agent_path)
    agent["channel_schema_version"] = 4
    agent["channels"] = {
        "feishu": {
            "name": "Feishu",
            "enabled": True,
            "settings": {},
        },
    }
    _write_json(agent_path, agent)
    chats_path = workspace / "chats.json"
    session_path = (
        workspace
        / "sessions"
        / "feishu"
        / session_filename("conversation", "ou-user")
    )
    _write_json(
        chats_path,
        {
            "version": 1,
            "chats": [
                {
                    "id": "chat-id",
                    "name": "Feishu",
                    "session_id": "conversation",
                    "user_id": "ou-user",
                    "channel": "feishu",
                },
            ],
        },
    )
    _write_json(session_path, {"agent": {"state": {"context": []}}})
    chats_before = chats_path.read_bytes()
    session_before = session_path.read_bytes()

    migrate_channel_configuration(config_path)

    migrated = _read_json(agent_path)
    assert migrated["channels"]["feishu"]["type"] == "feishu"
    assert chats_path.read_bytes() == chats_before
    assert session_path.read_bytes() == session_before


def test_migration_merges_instance_qualified_session_history(
    tmp_path: Path,
) -> None:
    config_path, agent_path = _install(tmp_path)
    workspace = agent_path.parent
    agent = _read_json(agent_path)
    agent["channel_schema_version"] = 2
    agent["channels"] = [
        {
            "id": "feishu-main",
            "type": "feishu",
            "name": "Feishu",
            "settings": {},
        },
    ]
    _write_json(agent_path, agent)
    user_id = "ou-user"
    logical_id = "conversation"
    chats_path = workspace / "chats.json"
    _write_json(
        chats_path,
        {
            "version": 1,
            "chats": [
                {
                    "id": "chat-id",
                    "name": "Feishu",
                    "session_id": logical_id,
                    "user_id": user_id,
                    "channel": "feishu",
                },
            ],
        },
    )
    session_dir = workspace / "sessions" / "feishu"
    old_path = session_dir / session_filename(logical_id, user_id)
    qualified_path = session_dir / session_filename(
        f"feishu-main:{logical_id}",
        user_id,
    )
    _write_json(
        old_path,
        {"agent": {"state": {"context": [{"id": "old"}]}}},
    )
    _write_json(
        qualified_path,
        {"agent": {"state": {"context": [{"id": "new"}]}}},
    )

    migrate_channel_configuration(config_path)

    merged = _read_json(old_path)
    assert [item["id"] for item in merged["agent"]["state"]["context"]] == [
        "old",
        "new",
    ]
    assert not qualified_path.exists()


@pytest.mark.parametrize(
    ("channel_type", "state_name"),
    [
        ("feishu", "feishu_receive_ids.json"),
        ("dingtalk", "dingtalk_session_webhooks.json"),
        ("yuanbao", "yuanbao_sessions.json"),
    ],
)
def test_migration_restores_instance_state_to_agent_workspace(
    tmp_path: Path,
    channel_type: str,
    state_name: str,
) -> None:
    config_path, agent_path = _install(tmp_path)
    workspace = agent_path.parent
    instance_id = f"{channel_type}-main"
    agent = _read_json(agent_path)
    agent["channel_schema_version"] = 2
    agent["channels"] = [
        {
            "id": instance_id,
            "type": channel_type,
            "name": channel_type.title(),
            "settings": {},
        },
    ]
    _write_json(agent_path, agent)
    digest = hashlib.sha256(instance_id.encode("utf-8")).hexdigest()[:16]
    instance_path = workspace / ".channel_instances" / digest / state_name
    canonical_path = workspace / state_name
    _write_json(canonical_path, {"legacy": True})
    _write_json(instance_path, {"current": True})

    migrate_channel_configuration(config_path)

    assert _read_json(canonical_path) == {"current": True}
    assert not instance_path.exists()


def test_v4_to_v5_leaves_session_and_state_files_untouched(
    tmp_path: Path,
) -> None:
    config_path, agent_path = _install(tmp_path)
    workspace = agent_path.parent
    instance_id = "feishu-main"
    agent = _read_json(agent_path)
    agent["channel_schema_version"] = 4
    agent["channels"] = {
        "feishu": {
            "name": "Feishu",
            "enabled": True,
            "settings": {},
        },
    }
    _write_json(agent_path, agent)
    backup_path = (
        tmp_path
        / "migrations"
        / "channel-config-v3"
        / "old"
        / "workspaces"
        / "sales"
        / "agent.json"
    )
    backup = dict(agent)
    backup["channel_schema_version"] = 2
    backup["channels"] = [
        {
            "id": instance_id,
            "type": "feishu",
            "name": "Feishu",
            "settings": {},
        },
    ]
    _write_json(backup_path, backup)
    _write_json(workspace / "chats.json", {"version": 1, "chats": []})
    session_dir = workspace / "sessions" / "feishu"
    canonical_path = session_dir / session_filename(
        "conversation",
        "ou-user",
    )
    qualified_path = session_dir / session_filename(
        f"{instance_id}:conversation",
        "ou-user",
    )
    _write_json(
        canonical_path,
        {"agent": {"state": {"context": [{"id": "old"}]}}},
    )
    _write_json(
        qualified_path,
        {"agent": {"state": {"context": [{"id": "new"}]}}},
    )
    digest = hashlib.sha256(instance_id.encode("utf-8")).hexdigest()[:16]
    instance_state = (
        workspace / ".channel_instances" / digest / "feishu_receive_ids.json"
    )
    _write_json(instance_state, {"event": 1})

    migrate_channel_configuration(config_path)

    migrated = _read_json(agent_path)
    assert migrated["channel_schema_version"] == 5
    assert migrated["channels"]["feishu"]["type"] == "feishu"
    assert qualified_path.exists()
    assert [
        item["id"]
        for item in _read_json(canonical_path)["agent"]["state"]["context"]
    ] == ["old"]
    chats = _read_json(workspace / "chats.json")["chats"]
    assert chats == []
    assert not (workspace / "feishu_receive_ids.json").exists()
    assert instance_state.exists()


def test_migrates_legacy_channel_map_into_type_keyed_configs(
    tmp_path: Path,
) -> None:
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
    telegram = migrated["channels"]["telegram"]
    assert telegram == {
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


def test_migrates_onebot_download_limit_without_data_loss(
    tmp_path: Path,
) -> None:
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

    migrate_channel_configuration(config_path)

    channels = _read_json(agent_path)["channels"]
    assert channels["onebot"]["settings"]["media_download_max_mb"] == 75


def test_routing_migration_keeps_multiple_configs_of_same_type(
    tmp_path: Path,
) -> None:
    config_path, agent_path = _install(tmp_path)
    root = _read_json(config_path)
    root["channel_routing"] = {
        "migration_version": 1,
        "endpoints": [
            {
                "endpoint_id": "telegram-main",
                "channel_key": "telegram",
                "account_id": "Main Bot",
                "enabled": True,
                "settings": {"bot_token": "main"},
            },
            {
                "endpoint_id": "telegram-backup",
                "channel_key": "telegram",
                "account_id": "Backup Bot",
                "enabled": True,
                "settings": {"bot_token": "backup"},
            },
        ],
        "bindings": [
            {
                "binding_id": "main-sales",
                "endpoint_id": "telegram-main",
                "agent_id": "sales",
                "enabled": True,
            },
            {
                "binding_id": "backup-sales",
                "endpoint_id": "telegram-backup",
                "agent_id": "sales",
                "enabled": False,
            },
        ],
    }
    _write_json(config_path, root)

    migrate_channel_configuration(config_path)

    channels = _read_json(agent_path)["channels"]
    assert list(channels) == ["telegram", "telegram-backup"]
    assert channels["telegram"]["enabled"] is True
    assert channels["telegram-backup"]["enabled"] is False


def test_migrates_projected_endpoint_to_channel_type(
    tmp_path: Path,
) -> None:
    config_path, agent_path = _install(tmp_path)
    root = _read_json(config_path)
    root["channel_routing"] = {
        "migration_version": 1,
        "endpoints": [
            {
                "endpoint_id": "telegram:sales",
                "channel_key": "telegram",
                "account_id": "sales",
                "settings": {"bot_token": "secret"},
            },
        ],
        "bindings": [
            {
                "binding_id": "telegram:sales->sales",
                "endpoint_id": "telegram:sales",
                "agent_id": "sales",
            },
        ],
    }
    _write_json(config_path, root)

    migrate_channel_configuration(config_path)

    channels = _read_json(agent_path)["channels"]
    assert channels["telegram"]["settings"]["bot_token"] == "secret"


def test_routing_migration_uses_the_single_enabled_owner(
    tmp_path: Path,
) -> None:
    config_path, sales_path = _install(tmp_path)
    support_workspace = tmp_path / "workspaces" / "support"
    support_path = support_workspace / "agent.json"
    _write_json(
        support_path,
        {"id": "support", "name": "Support", "channels": {}},
    )
    root = _read_json(config_path)
    root["agents"]["profiles"]["support"] = {
        "id": "support",
        "workspace_dir": str(support_workspace),
    }
    root["channel_routing"] = {
        "endpoints": [
            {
                "endpoint_id": "telegram:shared",
                "channel_key": "telegram",
                "account_id": "Shared",
                "settings": {},
            },
        ],
        "bindings": [
            {
                "binding_id": "shared-sales",
                "endpoint_id": "telegram:shared",
                "agent_id": "sales",
                "enabled": False,
            },
            {
                "binding_id": "shared-support",
                "endpoint_id": "telegram:shared",
                "agent_id": "support",
                "enabled": True,
            },
        ],
    }
    _write_json(config_path, root)

    migrate_channel_configuration(config_path)

    assert _read_json(sales_path)["channels"] == {}
    assert "telegram" in _read_json(support_path)["channels"]


def test_migration_assigns_root_map_to_active_agent(tmp_path: Path) -> None:
    config_path, agent_path = _install(tmp_path)
    root = _read_json(config_path)
    root["channels"] = {
        "telegram": {"enabled": True, "bot_token": "root-secret"},
    }
    _write_json(config_path, root)

    migrate_channel_configuration(config_path)

    assert "channels" not in _read_json(config_path)
    assert (
        _read_json(agent_path)["channels"]["telegram"]["settings"]["bot_token"]
        == "root-secret"
    )


def test_v4_agent_is_authoritative_over_stale_root_channels(
    tmp_path: Path,
) -> None:
    config_path, agent_path = _install(tmp_path)
    root = _read_json(config_path)
    root["channels"] = {
        "feishu": {"enabled": False, "app_id": "stale"},
    }
    _write_json(config_path, root)
    agent = _read_json(agent_path)
    agent["channel_schema_version"] = 4
    agent["channels"] = {
        "feishu": {
            "name": "Current",
            "enabled": True,
            "settings": {"app_id": "current"},
        },
    }
    _write_json(agent_path, agent)

    migrate_channel_configuration(config_path)

    assert "channels" not in _read_json(config_path)
    migrated = _read_json(agent_path)
    assert migrated["channels"]["feishu"]["settings"]["app_id"] == ("current")


def test_migration_is_idempotent(tmp_path: Path) -> None:
    config_path, _ = _install(tmp_path)
    root = _read_json(config_path)
    root["channel_routing"] = {
        "migration_version": 1,
        "endpoints": [],
        "bindings": [],
    }
    _write_json(config_path, root)

    first = migrate_channel_configuration(config_path)
    first_root = config_path.read_bytes()
    second = migrate_channel_configuration(config_path)

    assert first.migrated is True
    assert second.migrated is False
    assert second.backup_dir is None
    assert config_path.read_bytes() == first_root


def test_migration_rejects_unbound_endpoint_without_writes(
    tmp_path: Path,
) -> None:
    config_path, agent_path = _install(tmp_path)
    root = _read_json(config_path)
    root["channel_routing"] = {
        "migration_version": 1,
        "endpoints": [
            {
                "endpoint_id": "telegram-orphan",
                "channel_key": "telegram",
                "account_id": "Orphan",
                "settings": {},
            },
        ],
        "bindings": [],
    }
    _write_json(config_path, root)
    original_root = config_path.read_bytes()
    original_agent = agent_path.read_bytes()

    with pytest.raises(ChannelMigrationError, match="no agent owner"):
        migrate_channel_configuration(config_path)

    assert config_path.read_bytes() == original_root
    assert agent_path.read_bytes() == original_agent


def test_migration_preserves_conflicting_type_as_secondary_instance(
    tmp_path: Path,
) -> None:
    config_path, agent_path = _install(tmp_path)
    agent = _read_json(agent_path)
    agent["channels"] = [
        {
            "id": "telegram-main",
            "type": "telegram",
            "name": "Existing",
            "enabled": True,
            "settings": {"bot_token": "existing"},
        },
    ]
    _write_json(agent_path, agent)
    root = _read_json(config_path)
    root["channel_routing"] = {
        "migration_version": 1,
        "endpoints": [
            {
                "endpoint_id": "telegram-main",
                "channel_key": "telegram",
                "account_id": "Imported",
                "settings": {"bot_token": "different"},
            },
        ],
        "bindings": [
            {
                "binding_id": "main-sales",
                "endpoint_id": "telegram-main",
                "agent_id": "sales",
            },
        ],
    }
    _write_json(config_path, root)
    migrate_channel_configuration(config_path)

    channels = _read_json(agent_path)["channels"]
    assert channels["telegram"]["settings"]["bot_token"] == "existing"
    assert channels["telegram-main"]["settings"]["bot_token"] == ("different")


def test_migration_creates_recoverable_backup_manifest(
    tmp_path: Path,
) -> None:
    config_path, agent_path = _install(tmp_path)
    root = _read_json(config_path)
    root["channel_routing"] = {
        "migration_version": 1,
        "endpoints": [],
        "bindings": [],
    }
    _write_json(config_path, root)

    result = migrate_channel_configuration(config_path)

    assert result.backup_dir is not None
    manifest = _read_json(result.backup_dir / "manifest.json")
    assert manifest["migration_version"] == (CHANNEL_RUNTIME_MIGRATION_VERSION)
    assert "config.json" in manifest["files"]
    assert agent_path.exists()


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
