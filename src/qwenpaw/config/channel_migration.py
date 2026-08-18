# -*- coding: utf-8 -*-
"""One-shot migration to agent-owned Channel instances."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ..utils.io_utils import get_sync_path_lock, write_json_atomic
from .config import AgentChannelConfig, AgentProfileConfig, Config
from ..domain.channels.catalog import get_channel_config_model
from ..utils.session_paths import (
    sanitize_session_filename,
    session_filename,
)

CHANNEL_RUNTIME_MIGRATION_VERSION = 5


class ChannelMigrationError(RuntimeError):
    """Raised when Channel data cannot be migrated safely."""


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


@dataclass(frozen=True, slots=True)
class _SessionRewrite:
    """One qualified Session file merged back into its logical identity."""

    canonical_path: Path
    qualified_path: Path
    merged_data: dict[str, Any]
    canonical_existed: bool


@dataclass(frozen=True, slots=True)
class _StateRewrite:
    """One V2 instance state file restored to the Agent workspace."""

    canonical_path: Path
    instance_path: Path
    data: dict[str, Any]
    canonical_existed: bool


@dataclass(frozen=True, slots=True)
class _ChatsRewrite:
    """One repaired Agent chat registry."""

    path: Path
    data: dict[str, Any]
    existed: bool


_CHANNEL_STATE_FILES = {
    "dingtalk": "dingtalk_session_webhooks.json",
    "feishu": "feishu_receive_ids.json",
    "yuanbao": "yuanbao_sessions.json",
}

_INSTANCE_ID_RE = re.compile(r"^(.+)-[0-9a-f]{8}$")
_INSTANCE_CONFIG_FIELDS = {"type", "name", "enabled", "settings"}


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


def _generated_primary_type(
    instance_id: str,
    channels: dict[str, Any],
) -> str | None:
    """Infer a generated secondary's type from its primary entry."""
    match = _INSTANCE_ID_RE.fullmatch(instance_id)
    if match is None:
        return None
    channel_type = match.group(1)
    primary = channels.get(channel_type)
    if not isinstance(primary, dict):
        return None
    primary_type = str(primary.get("type") or channel_type)
    return channel_type if primary_type == channel_type else None


def _is_wrapped_instance_config(value: object) -> bool:
    """Return whether a value uses the Agent-owned instance envelope."""
    return (
        isinstance(value, dict)
        and {"name", "settings"}.issubset(value)
        and set(value).issubset(_INSTANCE_CONFIG_FIELDS)
        and isinstance(value.get("settings"), dict)
    )


def _unwrap_nested_instance_config(
    value: dict[str, Any],
) -> dict[str, Any]:
    """Repair an instance envelope nested by a legacy flat migration."""
    nested = value.get("settings")
    if not isinstance(nested, dict) or not _is_wrapped_instance_config(
        nested,
    ):
        return value
    repaired = dict(nested)
    repaired.setdefault("enabled", bool(value.get("enabled", True)))
    return repaired


def channel_configuration_requires_migration(data: object) -> bool:
    """Return whether one Agent has pre-V5 or damaged Channel data."""
    if not isinstance(data, dict):
        return False
    channels = data.get("channels", {})
    if (
        not isinstance(channels, dict)
        or int(
            data.get("channel_schema_version") or 0,
        )
        != CHANNEL_RUNTIME_MIGRATION_VERSION
    ):
        return True
    for instance_id, value in channels.items():
        if not isinstance(value, dict) or not {
            "type",
            "name",
            "settings",
        }.issubset(value):
            return True
        inferred = _generated_primary_type(str(instance_id), channels)
        if inferred and str(value.get("type") or "") == instance_id:
            return True
    return False


def _agent_sources(
    config_path: Path,
    root: dict[str, Any],
) -> list[tuple[str, _SourceFile]]:
    profiles = (root.get("agents") or {}).get("profiles") or {}
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
            continue
        if _is_wrapped_instance_config(raw_value):
            channel = dict(raw_value)
            channel.setdefault("type", channel_type)
            wrapped_type = str(channel.get("type") or "")
            _validate_channel(wrapped_type, channel)
            channels[channel_type] = channel
            continue
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
        payload = dict(value)
        payload.setdefault("type", channel_type)
        channel = AgentChannelConfig.model_validate(payload)
        if channel.type != channel_type:
            raise ValueError(
                f"Channel type does not match instance data: "
                f"{channel.type} != {channel_type}",
            )
        channel.validate_for_type(channel_type)
    except (ValidationError, ValueError) as exc:
        raise ChannelMigrationError(
            f"Invalid Channel configuration {channel_type}: {exc}",
        ) from exc


def _v2_list_to_channels(
    values: list[Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, str], dict[str, list[str]]]:
    channels: dict[str, dict[str, Any]] = {}
    primary_instance_ids: dict[str, str] = {}
    secondary_instance_ids: dict[str, list[str]] = {}
    type_counts: dict[str, int] = {}
    old_instance_ids: set[str] = set()
    for value in values:
        if not isinstance(value, dict):
            raise ChannelMigrationError(
                "Channel configurations must be objects",
            )
        channel_type = str(value.get("type") or "")
        if not channel_type:
            raise ChannelMigrationError(
                "Channel configuration type must not be empty",
            )
        count = type_counts.get(channel_type, 0)
        old_instance_id = str(value.get("id") or "")
        if old_instance_id and old_instance_id in old_instance_ids:
            raise ChannelMigrationError(
                f"Duplicate Channel instance ID: {old_instance_id}",
            )
        if count == 0:
            instance_id = channel_type
            primary_instance_ids[channel_type] = (
                old_instance_id or channel_type
            )
        else:
            instance_id = old_instance_id or f"{channel_type}-{count + 1}"
            if instance_id == channel_type:
                raise ChannelMigrationError(
                    f"Duplicate Channel instance ID: {instance_id}",
                )
            secondary_instance_ids.setdefault(channel_type, []).append(
                instance_id,
            )
        if instance_id in channels:
            raise ChannelMigrationError(
                f"Duplicate Channel instance ID: {instance_id}",
            )
        channel = {
            "type": channel_type,
            "name": str(value.get("name") or channel_type.title()),
            "enabled": bool(value.get("enabled", True)),
            "settings": dict(value.get("settings") or {}),
        }
        _validate_channel(channel_type, channel)
        channels[instance_id] = channel
        if old_instance_id:
            old_instance_ids.add(old_instance_id)
        type_counts[channel_type] = count + 1
    return channels, primary_instance_ids, secondary_instance_ids


def _v3_backup_instance_ids(
    config_path: Path,
    source: _SourceFile,
) -> dict[str, str]:
    """Recover V2 instance IDs from the mandatory V3 backup."""
    backup_root = config_path.parent / "migrations" / "channel-config-v3"
    for backup_dir in sorted(backup_root.glob("*"), reverse=True):
        candidate = backup_dir / source.backup_name
        if not candidate.is_file():
            continue
        channels = _read_object(candidate).get("channels")
        if not isinstance(channels, list):
            continue
        _, instance_ids, _ = _v2_list_to_channels(channels)
        return instance_ids
    return {}


def _merge_channels(
    existing: dict[str, dict[str, Any]],
    additions: list[tuple[str, dict[str, Any], str]],
) -> tuple[dict[str, dict[str, Any]], dict[str, str], dict[str, list[str]]]:
    merged = dict(existing)
    primary_instance_ids: dict[str, str] = {}
    secondary_instance_ids: dict[str, list[str]] = {}
    for channel_type, value, instance_id in additions:
        _validate_channel(channel_type, value)
        has_type = any(
            str(item.get("type") or key) == channel_type
            for key, item in merged.items()
        )
        target_id = instance_id if has_type else channel_type
        if target_id in merged and merged[target_id] != value:
            raise ChannelMigrationError(
                f"Duplicate Channel instance ID: {target_id}",
            )
        migrated_value = dict(value)
        migrated_value["type"] = channel_type
        merged[target_id] = migrated_value
        if not has_type:
            primary_instance_ids[channel_type] = instance_id
        else:
            secondary_instance_ids.setdefault(channel_type, []).append(
                target_id,
            )
    return merged, primary_instance_ids, secondary_instance_ids


def _routing_additions(
    root: dict[str, Any],
    known_agents: set[str],
) -> dict[str, list[tuple[str, dict[str, Any], str]]]:
    routing = root.get("channel_routing")
    if routing is None:
        return {}
    if not isinstance(routing, dict):
        raise ChannelMigrationError("channel_routing must be an object")
    endpoints = routing.get("endpoints") or []
    bindings = routing.get("bindings") or []
    if not isinstance(endpoints, list) or not isinstance(bindings, list):
        raise ChannelMigrationError(
            "channel_routing endpoints and bindings must be lists",
        )
    owners: dict[str, list[dict[str, Any]]] = {}
    for binding in bindings:
        if not isinstance(binding, dict):
            raise ChannelMigrationError("Channel bindings must be objects")
        owners.setdefault(str(binding.get("endpoint_id") or ""), []).append(
            binding,
        )
    additions: dict[str, list[tuple[str, dict[str, Any], str]]] = {}
    for endpoint in endpoints:
        if not isinstance(endpoint, dict):
            raise ChannelMigrationError("Channel endpoints must be objects")
        endpoint_id = str(endpoint.get("endpoint_id") or "")
        endpoint_owners = owners.get(endpoint_id, [])
        if not endpoint_owners:
            raise ChannelMigrationError(
                f"Channel endpoint {endpoint_id} has no agent owner",
            )
        enabled_owners = [
            binding
            for binding in endpoint_owners
            if bool(binding.get("enabled", True))
        ]
        if len(enabled_owners) == 1:
            binding = enabled_owners[0]
        elif not enabled_owners and len(endpoint_owners) == 1:
            binding = endpoint_owners[0]
        else:
            raise ChannelMigrationError(
                f"Channel endpoint {endpoint_id} has ambiguous ownership",
            )
        agent_id = str(binding.get("agent_id") or "")
        if agent_id not in known_agents:
            raise ChannelMigrationError(
                f"Channel endpoint {endpoint_id} references missing "
                f"agent {agent_id}",
            )
        channel_type = str(endpoint.get("channel_key") or "")
        value = {
            "type": channel_type,
            "name": str(endpoint.get("account_id") or endpoint_id),
            "enabled": bool(endpoint.get("enabled", True))
            and bool(binding.get("enabled", True)),
            "settings": dict(endpoint.get("settings") or {}),
        }
        _validate_channel(channel_type, value)
        additions.setdefault(agent_id, []).append(
            (channel_type, value, endpoint_id),
        )
    return additions


def _message_key(message: Any) -> str:
    """Return a stable key used to deduplicate migrated messages."""
    if isinstance(message, dict) and message.get("id"):
        return f"id:{message['id']}"
    return f"json:{json.dumps(message, sort_keys=True, default=str)}"


def _merge_session_data(
    canonical: dict[str, Any],
    qualified: dict[str, Any],
) -> dict[str, Any]:
    """Keep the latest state while joining old and qualified histories."""
    merged = json.loads(json.dumps(qualified))
    old_state = (canonical.get("agent") or {}).get("state") or {}
    new_agent = merged.setdefault("agent", {})
    new_state = new_agent.setdefault("state", {})
    old_context = old_state.get("context") or []
    new_context = new_state.get("context") or []
    messages = []
    seen = set()
    for message in [*old_context, *new_context]:
        key = _message_key(message)
        if key in seen:
            continue
        seen.add(key)
        messages.append(message)
    new_state["context"] = messages
    return merged


# pylint: disable-next=too-many-branches,too-many-statements
def _session_rewrites(
    config_path: Path,
    agent_id: str,
    source: _SourceFile,
    instance_ids: dict[str, str],
    secondary_instance_ids: dict[str, list[str]],
) -> tuple[list[_SessionRewrite], list[_SourceFile], _ChatsRewrite | None]:
    """Plan Session file rewrites without modifying the filesystem."""
    if not instance_ids and not secondary_instance_ids:
        return [], [], None
    chats_path = source.path.parent / "chats.json"
    chats_existed = chats_path.is_file()
    chats_data = (
        _read_object(chats_path)
        if chats_existed
        else {"version": 1, "chats": []}
    )
    chats = chats_data.get("chats") or []
    if not isinstance(chats, list):
        raise ChannelMigrationError(
            f"Agent {agent_id} chats.json chats must be a list",
        )
    rewrites = []
    sources = []
    seen_paths: set[Path] = set()
    discovered: dict[Path, tuple[str, str, str]] = {}
    for channel_type, instance_id in instance_ids.items():
        session_dir = source.path.parent / "sessions" / channel_type
        for chat in chats:
            if not isinstance(chat, dict):
                continue
            if str(chat.get("channel") or "") != channel_type:
                continue
            logical_id = str(chat.get("session_id") or "")
            user_id = str(chat.get("user_id") or "")
            if not logical_id or logical_id.startswith(f"{instance_id}:"):
                continue
            qualified_path = session_dir / session_filename(
                f"{instance_id}:{logical_id}",
                user_id,
            )
            if qualified_path.is_file():
                discovered[qualified_path] = (
                    channel_type,
                    logical_id,
                    user_id,
                )

        marker = f"{sanitize_session_filename(instance_id)}--"
        if session_dir.is_dir():
            for qualified_path in session_dir.glob("*.json"):
                index = qualified_path.stem.rfind(marker)
                if index < 0:
                    continue
                prefix = qualified_path.stem[:index]
                logical_id = qualified_path.stem[index + len(marker) :]
                user_id = prefix[:-1] if prefix.endswith("_") else ""
                if logical_id:
                    discovered.setdefault(
                        qualified_path,
                        (channel_type, logical_id, user_id),
                    )

    chats_changed = False
    for qualified_path, identity in sorted(
        discovered.items(),
        key=lambda item: str(item[0]),
    ):
        channel_type, logical_id, user_id = identity
        canonical_path = qualified_path.with_name(
            session_filename(logical_id, user_id),
        )
        canonical = (
            _read_object(canonical_path) if canonical_path.is_file() else {}
        )
        qualified = _read_object(qualified_path)
        rewrites.append(
            _SessionRewrite(
                canonical_path=canonical_path,
                qualified_path=qualified_path,
                merged_data=_merge_session_data(canonical, qualified),
                canonical_existed=canonical_path.is_file(),
            ),
        )
        for path in (canonical_path, qualified_path):
            if not path.is_file() or path in seen_paths:
                continue
            try:
                relative = path.resolve().relative_to(
                    config_path.parent.resolve(),
                )
            except ValueError:
                relative = (
                    Path("external")
                    / agent_id
                    / "sessions"
                    / channel_type
                    / path.name
                )
            sources.append(_SourceFile(path, relative, _read_object(path)))
            seen_paths.add(path)
        exists = any(
            isinstance(chat, dict)
            and str(chat.get("session_id") or "") == logical_id
            and str(chat.get("user_id") or "") == user_id
            and str(chat.get("channel") or "") == channel_type
            for chat in chats
        )
        if not exists:
            chats.append(
                {
                    "id": str(uuid.uuid4()),
                    "name": f"Migrated {channel_type.title()} chat",
                    "session_id": logical_id,
                    "user_id": user_id,
                    "channel": channel_type,
                },
            )
            chats_changed = True

    for channel_type, secondary_ids in secondary_instance_ids.items():
        session_dir = source.path.parent / "sessions" / channel_type
        for instance_id in secondary_ids:
            secondary_sessions: set[tuple[str, str]] = set()
            for chat in chats:
                if not isinstance(chat, dict):
                    continue
                if str(chat.get("channel") or "") != channel_type:
                    continue
                logical_id = str(chat.get("session_id") or "")
                user_id = str(chat.get("user_id") or "")
                if not logical_id or logical_id.startswith(
                    f"{instance_id}:",
                ):
                    continue
                qualified_path = session_dir / session_filename(
                    f"{instance_id}:{logical_id}",
                    user_id,
                )
                if qualified_path.is_file():
                    secondary_sessions.add((logical_id, user_id))

            marker = f"{sanitize_session_filename(instance_id)}--"
            if session_dir.is_dir():
                for qualified_path in session_dir.glob("*.json"):
                    index = qualified_path.stem.rfind(marker)
                    if index < 0:
                        continue
                    prefix = qualified_path.stem[:index]
                    logical_id = qualified_path.stem[index + len(marker) :]
                    user_id = prefix[:-1] if prefix.endswith("_") else ""
                    if logical_id:
                        secondary_sessions.add((logical_id, user_id))

            for logical_id, user_id in sorted(secondary_sessions):
                qualified_id = f"{instance_id}:{logical_id}"
                existing_chat = next(
                    (
                        chat
                        for chat in chats
                        if isinstance(chat, dict)
                        and str(chat.get("session_id") or "") == qualified_id
                        and str(chat.get("user_id") or "") == user_id
                        and str(chat.get("channel") or "") == channel_type
                    ),
                    None,
                )
                if existing_chat is None:
                    chats.append(
                        {
                            "id": str(uuid.uuid4()),
                            "name": (f"Migrated {channel_type.title()} chat"),
                            "session_id": qualified_id,
                            "user_id": user_id,
                            "channel": channel_type,
                            "meta": {
                                "channel_instance_id": instance_id,
                            },
                        },
                    )
                    chats_changed = True
                    continue
                meta = existing_chat.setdefault("meta", {})
                if not isinstance(meta, dict):
                    meta = {}
                    existing_chat["meta"] = meta
                if meta.get("channel_instance_id") != instance_id:
                    meta["channel_instance_id"] = instance_id
                    chats_changed = True

    chats_rewrite = None
    if chats_changed:
        chats_data["chats"] = chats
        chats_rewrite = _ChatsRewrite(
            path=chats_path,
            data=chats_data,
            existed=chats_existed,
        )
        if chats_existed:
            try:
                relative = chats_path.resolve().relative_to(
                    config_path.parent.resolve(),
                )
            except ValueError:
                relative = Path("external") / agent_id / "chats.json"
            sources.append(
                _SourceFile(chats_path, relative, _read_object(chats_path)),
            )
    return rewrites, sources, chats_rewrite


def _state_rewrites(
    config_path: Path,
    agent_id: str,
    source: _SourceFile,
    instance_ids: dict[str, str],
) -> tuple[list[_StateRewrite], list[_SourceFile]]:
    """Plan restoration of state written by the V2 instance runtime."""
    rewrites = []
    sources = []
    workspace = source.path.parent
    for channel_type, instance_id in instance_ids.items():
        state_name = _CHANNEL_STATE_FILES.get(channel_type)
        if state_name is None:
            continue
        digest = hashlib.sha256(
            instance_id.encode("utf-8"),
        ).hexdigest()[:16]
        instance_path = workspace / ".channel_instances" / digest / state_name
        if not instance_path.is_file():
            continue
        canonical_path = workspace / state_name
        rewrites.append(
            _StateRewrite(
                canonical_path=canonical_path,
                instance_path=instance_path,
                data=_read_object(instance_path),
                canonical_existed=canonical_path.is_file(),
            ),
        )
        for path in (canonical_path, instance_path):
            if not path.is_file():
                continue
            try:
                relative = path.resolve().relative_to(
                    config_path.parent.resolve(),
                )
            except ValueError:
                relative = (
                    Path("external")
                    / agent_id
                    / "channel-state"
                    / (
                        f"{digest}-{state_name}"
                        if path == instance_path
                        else state_name
                    )
                )
            sources.append(_SourceFile(path, relative, _read_object(path)))
    return rewrites, sources


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


# pylint: disable-next=too-many-statements,too-many-branches
def migrate_channel_configuration(
    config_path: Path,
) -> ChannelMigrationResult:
    """Persist stable Channel instances and preserve primary history."""
    config_path = Path(config_path).expanduser().resolve()
    if not config_path.is_file():
        return ChannelMigrationResult(False)
    with get_sync_path_lock(config_path):
        root = _read_object(config_path)
        root_source = _SourceFile(
            config_path,
            Path("config.json"),
            root,
        )
        agent_sources = _agent_sources(config_path, root)
        source_by_agent = dict(agent_sources)
        known_agents = set(source_by_agent)
        additions = _routing_additions(root, known_agents)

        root_legacy = root.get("channels")
        if isinstance(root_legacy, dict):
            active_agent = str(
                (root.get("agents") or {}).get("active_agent") or "default",
            )
            target = source_by_agent.get(active_agent)
            if target is None:
                raise ChannelMigrationError(
                    f"Cannot assign root channels to active agent "
                    f"{active_agent}: agent.json is missing",
                )
            target_schema = int(
                target.data.get("channel_schema_version") or 0,
            )
            if target_schema < 4:
                current = target.data.get("channels")
                if (
                    isinstance(current, dict)
                    and current
                    and current != root_legacy
                ):
                    raise ChannelMigrationError(
                        f"Root channels conflict with agent {active_agent}",
                    )
                target.data["channels"] = dict(root_legacy)

        changed_agents = []
        changed_sources = []
        session_rewrites: list[_SessionRewrite] = []
        session_sources: list[_SourceFile] = []
        state_rewrites: list[_StateRewrite] = []
        state_sources: list[_SourceFile] = []
        chats_rewrites: list[_ChatsRewrite] = []
        for agent_id, source in agent_sources:
            raw_channels = source.data.get("channels", {})
            schema_version = int(
                source.data.get("channel_schema_version") or 0,
            )
            changed = False
            existing_instance_ids: dict[str, str] = {}
            existing_secondary_ids: dict[str, list[str]] = {}
            if isinstance(raw_channels, list):
                (
                    existing,
                    existing_instance_ids,
                    existing_secondary_ids,
                ) = _v2_list_to_channels(raw_channels)
                changed = True
            elif isinstance(raw_channels, dict) and schema_version < 3:
                existing = _legacy_map_to_channels(
                    agent_id,
                    source.data,
                    raw_channels,
                )
                changed = True
            elif isinstance(raw_channels, dict):
                existing = {}
                for instance_id, channel in raw_channels.items():
                    if not isinstance(channel, dict):
                        raise ChannelMigrationError(
                            f"Agent {agent_id} Channel {instance_id} "
                            f"must be an object",
                        )
                    migrated_channel = _unwrap_nested_instance_config(
                        dict(channel),
                    )
                    if schema_version < 5:
                        migrated_channel.setdefault("type", instance_id)
                    inferred_type = _generated_primary_type(
                        str(instance_id),
                        raw_channels,
                    )
                    if (
                        inferred_type
                        and migrated_channel.get("type") == instance_id
                    ):
                        migrated_channel["type"] = inferred_type
                    channel_type = str(
                        migrated_channel.get("type") or "",
                    )
                    _validate_channel(channel_type, migrated_channel)
                    existing[instance_id] = migrated_channel
                if schema_version == 3:
                    existing_instance_ids = _v3_backup_instance_ids(
                        config_path,
                        source,
                    )
            else:
                raise ChannelMigrationError(
                    f"Agent {agent_id} channels must be an object",
                )
            (
                merged,
                added_instance_ids,
                added_secondary_ids,
            ) = _merge_channels(existing, additions.get(agent_id, []))
            instance_ids = {
                **existing_instance_ids,
                **added_instance_ids,
            }
            secondary_instance_ids = dict(existing_secondary_ids)
            for channel_type, instance_id_list in added_secondary_ids.items():
                secondary_instance_ids.setdefault(channel_type, []).extend(
                    instance_id_list,
                )
            if merged != raw_channels:
                changed = True
            if source.data.get("channel_schema_version") != (
                CHANNEL_RUNTIME_MIGRATION_VERSION
            ):
                changed = True
            if changed:
                source.data["channels"] = merged
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
            rewrites, rewrite_sources, chats_rewrite = _session_rewrites(
                config_path,
                agent_id,
                source,
                instance_ids,
                secondary_instance_ids,
            )
            session_rewrites.extend(rewrites)
            session_sources.extend(rewrite_sources)
            if chats_rewrite is not None:
                chats_rewrites.append(chats_rewrite)
            rewrites_state, rewrite_state_sources = _state_rewrites(
                config_path,
                agent_id,
                source,
                instance_ids,
            )
            state_rewrites.extend(rewrites_state)
            state_sources.extend(rewrite_state_sources)

        root_changed = "channels" in root or "channel_routing" in root
        root.pop("channels", None)
        root.pop("channel_routing", None)
        try:
            Config.model_validate(root)
        except ValidationError as exc:
            raise ChannelMigrationError(
                f"Invalid migrated root configuration: {exc}",
            ) from exc
        if (
            not root_changed
            and not changed_sources
            and not session_rewrites
            and not state_rewrites
            and not chats_rewrites
        ):
            return ChannelMigrationResult(False)

        sources = [
            *([root_source] if root_changed else []),
            *changed_sources,
            *session_sources,
            *state_sources,
        ]
        backup_dir = _backup_sources(config_path, sources)
        created_paths = [
            rewrite.canonical_path
            for rewrite in session_rewrites
            if not rewrite.canonical_existed
        ]
        created_paths.extend(
            rewrite.canonical_path
            for rewrite in state_rewrites
            if not rewrite.canonical_existed
        )
        created_paths.extend(
            rewrite.path for rewrite in chats_rewrites if not rewrite.existed
        )
        try:
            if root_changed:
                write_json_atomic(config_path, root)
            for source in changed_sources:
                write_json_atomic(source.path, source.data)
            for rewrite in session_rewrites:
                write_json_atomic(
                    rewrite.canonical_path,
                    rewrite.merged_data,
                )
            for rewrite in state_rewrites:
                write_json_atomic(
                    rewrite.canonical_path,
                    rewrite.data,
                )
            for rewrite in chats_rewrites:
                write_json_atomic(rewrite.path, rewrite.data)
            for rewrite in session_rewrites:
                rewrite.qualified_path.unlink()
            for rewrite in state_rewrites:
                rewrite.instance_path.unlink()
        except Exception as exc:
            for path in created_paths:
                path.unlink(missing_ok=True)
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
