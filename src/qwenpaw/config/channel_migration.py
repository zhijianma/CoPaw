# -*- coding: utf-8 -*-
"""One-shot migration from the original flat Channel configuration."""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ..domain.channels.catalog import get_channel_config_model
from ..utils.io_utils import get_sync_path_lock, write_json_atomic
from .config import AgentChannelConfig, AgentProfileConfig, Config

CHANNEL_RUNTIME_MIGRATION_VERSION = 5
_INSTANCE_CONFIG_FIELDS = {"type", "name", "enabled", "settings"}


class ChannelMigrationError(RuntimeError):
    """Raised when original Channel data cannot be migrated safely."""


@dataclass(frozen=True, slots=True)
class ChannelMigrationResult:
    """Summary of one Channel migration attempt."""

    migrated: bool
    migrated_agents: tuple[str, ...] = ()
    backup_dir: Path | None = None


@dataclass(frozen=True, slots=True)
class _SourceFile:
    path: Path
    backup_name: Path
    data: dict[str, Any]


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ChannelMigrationError(
            f"Cannot read migration source {path}: {exc}",
        ) from exc
    if not isinstance(value, dict):
        raise ChannelMigrationError(
            f"Migration source must contain a JSON object: {path}",
        )
    return value


def _is_instance_config(value: object) -> bool:
    return (
        isinstance(value, dict)
        and {"type", "name", "settings"}.issubset(value)
        and set(value).issubset(_INSTANCE_CONFIG_FIELDS)
        and isinstance(value.get("settings"), dict)
    )


def _channel_map_kind(channels: object) -> str:
    """Classify only the original and the current persistent formats."""
    if not isinstance(channels, dict):
        return "development"
    if not channels:
        return "current"
    values = list(channels.values())
    if not all(isinstance(value, dict) for value in values):
        return "invalid"
    wrapped = [_is_instance_config(value) for value in values]
    if all(wrapped):
        return "current"
    if not any(wrapped):
        return "original"
    return "mixed"


def channel_configuration_requires_migration(data: object) -> bool:
    """Return whether an Agent contains the original flat Channel map."""
    if not isinstance(data, dict):
        return False
    return _channel_map_kind(data.get("channels", {})) == "original"


def _agent_sources(
    config_path: Path,
    root: dict[str, Any],
) -> list[tuple[str, _SourceFile]]:
    agents = root.get("agents") or {}
    profiles = agents.get("profiles") if isinstance(agents, dict) else None
    if not isinstance(profiles, dict):
        raise ChannelMigrationError("agents.profiles must be an object")
    sources = []
    for agent_id, profile in sorted(profiles.items()):
        if not isinstance(profile, dict):
            continue
        workspace = str(profile.get("workspace_dir") or "").strip()
        if not workspace:
            continue
        path = Path(workspace).expanduser() / "agent.json"
        if not path.is_file():
            continue
        try:
            relative = path.resolve().relative_to(
                config_path.parent.resolve(),
            )
        except ValueError:
            relative = Path("external") / str(agent_id) / "agent.json"
        sources.append(
            (
                str(agent_id),
                _SourceFile(path, relative, _read_object(path)),
            ),
        )
    return sources


def _migrate_display_fields(value: dict[str, Any]) -> None:
    filter_tools = value.pop("filter_tool_messages", None)
    if filter_tools is not None:
        value.setdefault("show_tool_calls", not bool(filter_tools))
        value.setdefault("show_tool_results", not bool(filter_tools))
    filter_thinking = value.pop("filter_thinking", None)
    if filter_thinking is not None:
        value.setdefault("show_thinking", not bool(filter_thinking))


def _is_meaningful(channel_type: str, value: dict[str, Any]) -> bool:
    if bool(value.get("enabled", False)):
        return True
    model = get_channel_config_model(channel_type)
    if model is None:
        return bool(value)
    defaults = model().model_dump(mode="json")
    return any(
        key != "enabled" and item != defaults.get(key)
        for key, item in value.items()
    )


def _migrate_console(
    agent_id: str,
    data: dict[str, Any],
    legacy: dict[str, Any],
) -> None:
    model = get_channel_config_model("console")
    if model is None:
        raise ChannelMigrationError("Console transport model is missing")
    transports = data.setdefault("transports", {})
    if not isinstance(transports, dict):
        raise ChannelMigrationError(
            f"Agent {agent_id} transports must be an object",
        )
    try:
        migrated = model.model_validate(legacy)
        current = model.model_validate(transports.get("console") or {})
    except ValidationError as exc:
        raise ChannelMigrationError(
            f"Invalid console configuration: {exc}",
        ) from exc
    if current not in (model(), migrated):
        raise ChannelMigrationError(
            f"Legacy console conflicts with agent {agent_id} transport",
        )
    transports["console"] = migrated.model_dump(mode="json")


def _validate_channel(
    channel_type: str,
    value: dict[str, Any],
) -> None:
    try:
        channel = AgentChannelConfig.model_validate(value)
        if channel.type != channel_type:
            raise ValueError(
                "Channel type does not match original map key: "
                f"{channel.type} != {channel_type}",
            )
        channel.validate_for_type(channel_type)
    except (ValidationError, ValueError) as exc:
        raise ChannelMigrationError(
            f"Invalid Channel configuration {channel_type}: {exc}",
        ) from exc


def _legacy_map_to_channels(
    agent_id: str,
    data: dict[str, Any],
    legacy: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    values = dict(legacy)
    if "weixin" in values:
        values.setdefault("wechat", values.pop("weixin"))
    console = values.pop("console", None)
    if isinstance(console, dict):
        _migrate_console(agent_id, data, console)

    channels = {}
    for channel_type, raw_value in sorted(values.items()):
        if not isinstance(raw_value, dict):
            raise ChannelMigrationError(
                f"Original Channel {channel_type} must be an object",
            )
        raw = dict(raw_value)
        _migrate_display_fields(raw)
        if not _is_meaningful(channel_type, raw):
            continue
        enabled = bool(raw.pop("enabled", False))
        channel = {
            "type": channel_type,
            "name": channel_type.replace("_", " ").title(),
            "enabled": enabled,
            "settings": raw,
        }
        _validate_channel(channel_type, channel)
        channels[channel_type] = channel
    return channels


def _unsupported_format(agent_id: str, kind: str) -> None:
    if kind == "development":
        detail = "unsupported development Channel format"
    else:
        detail = f"unsupported {kind} Channel format"
    raise ChannelMigrationError(f"Agent {agent_id} has {detail}")


def _backup_sources(
    config_path: Path,
    sources: list[_SourceFile],
) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = (
        config_path.parent
        / "migrations"
        / "channel-config-v5"
        / f"{stamp}-{uuid.uuid4().hex[:8]}"
    )
    files = []
    checksums = {}
    for source in sources:
        target = backup_dir / source.backup_name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source.path, target)
        name = source.backup_name.as_posix()
        files.append(name)
        checksums[name] = hashlib.sha256(target.read_bytes()).hexdigest()
    write_json_atomic(
        backup_dir / "manifest.json",
        {
            "migration_version": CHANNEL_RUNTIME_MIGRATION_VERSION,
            "files": sorted(files),
            "sha256": checksums,
        },
    )
    return backup_dir


def _restore_sources(
    backup_dir: Path,
    sources: list[_SourceFile],
) -> None:
    for source in sources:
        backup = backup_dir / source.backup_name
        source.path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup, source.path)


def _invalidate_config_caches() -> None:
    from . import utils as config_utils

    with config_utils._config_lock:  # pylint: disable=protected-access
        config_utils._config_cache = None  # pylint: disable=protected-access
        config_utils._config_mtime = None  # pylint: disable=protected-access
    with config_utils._agent_config_lock:  # pylint: disable=protected-access
        # pylint: disable-next=protected-access
        config_utils._agent_config_cache.clear()


def migrate_channel_configuration(
    config_path: Path,
) -> ChannelMigrationResult:
    """Migrate original flat maps; never reinterpret development formats."""
    config_path = Path(config_path).expanduser().resolve()
    if not config_path.is_file():
        return ChannelMigrationResult(False)

    with get_sync_path_lock(config_path):
        root = _read_object(config_path)
        root_source = _SourceFile(config_path, Path("config.json"), root)
        agent_sources = _agent_sources(config_path, root)
        source_by_agent = dict(agent_sources)

        root_changed = "channels" in root
        if root_changed:
            root_channels = root.get("channels")
            root_kind = _channel_map_kind(root_channels)
            if root_kind not in {"original", "current"}:
                _unsupported_format("root", root_kind)
            if root_kind == "current" and root_channels:
                _unsupported_format("root", "development")
            active_agent = str(
                (root.get("agents") or {}).get("active_agent") or "default",
            )
            target = source_by_agent.get(active_agent)
            if target is None:
                raise ChannelMigrationError(
                    "Cannot assign original root channels to active agent "
                    f"{active_agent}: agent.json is missing",
                )
            current = target.data.get("channels", {})
            if root_channels and current and current != root_channels:
                raise ChannelMigrationError(
                    f"Root channels conflict with agent {active_agent}",
                )
            if root_channels:
                target.data["channels"] = dict(root_channels)
            root.pop("channels", None)

        changed_agents = []
        changed_sources = []
        for agent_id, source in agent_sources:
            raw_channels = source.data.get("channels", {})
            kind = _channel_map_kind(raw_channels)
            if kind == "current":
                continue
            if kind != "original":
                _unsupported_format(agent_id, kind)
            source.data["channels"] = _legacy_map_to_channels(
                agent_id,
                source.data,
                raw_channels,
            )
            source.data[
                "channel_schema_version"
            ] = CHANNEL_RUNTIME_MIGRATION_VERSION
            try:
                AgentProfileConfig.model_validate(source.data)
            except ValidationError as exc:
                raise ChannelMigrationError(
                    f"Invalid migrated agent {agent_id}: {exc}",
                ) from exc
            changed_agents.append(agent_id)
            changed_sources.append(source)

        if not root_changed and not changed_sources:
            return ChannelMigrationResult(False)

        try:
            Config.model_validate(root)
        except ValidationError as exc:
            raise ChannelMigrationError(
                f"Invalid migrated root configuration: {exc}",
            ) from exc

        sources = [
            *([root_source] if root_changed else []),
            *changed_sources,
        ]
        backup_dir = _backup_sources(config_path, sources)
        try:
            if root_changed:
                write_json_atomic(config_path, root)
            for source in changed_sources:
                write_json_atomic(source.path, source.data)
        except Exception as exc:
            _restore_sources(backup_dir, sources)
            raise ChannelMigrationError(
                f"Channel migration write failed: {exc}",
            ) from exc

        _invalidate_config_caches()
        return ChannelMigrationResult(
            True,
            tuple(changed_agents),
            backup_dir,
        )


__all__ = [
    "CHANNEL_RUNTIME_MIGRATION_VERSION",
    "ChannelMigrationError",
    "ChannelMigrationResult",
    "channel_configuration_requires_migration",
    "migrate_channel_configuration",
]
