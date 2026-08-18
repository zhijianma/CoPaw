# -*- coding: utf-8 -*-
"""CLI channel: list and interactively configure channels in config.json."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any, Optional

import click
from pydantic import BaseModel
from qwenpaw.exceptions import (
    AppBaseException,
)

from ..config.config import (
    AgentProfileConfig,
    Config,
    ConsoleTransportConfig,
    load_agent_config,
    save_agent_config,
)
from .utils import prompt_confirm, prompt_select
from .http import client, print_json, resolve_base_url
from ..config import (
    get_available_channels,
    load_config,
)
from ..app.channels.config_service import ChannelConfigService
from ..app.channels.registry import get_channel_registry
from ..domain.channels.catalog import (
    BUILTIN_CHANNEL_CATALOG,
    get_channel_config_model,
)
from ..domain.channels.schema import (
    channel_config_fields_from_model,
    is_channel_secret_field,
)

CHANNEL_NAMES = {item.key: item.label for item in BUILTIN_CHANNEL_CATALOG}


def _get_channel_names() -> dict[str, str]:
    """Return channel key -> display name (built-in + plugins)."""
    available = get_available_channels()
    registry = get_channel_registry()
    out = {k: v for k, v in CHANNEL_NAMES.items() if k in available}
    for key in available:
        if key not in out and key in registry:
            cls = registry[key]
            out[key] = (
                getattr(cls, "display_name", None)
                or key.replace(
                    "_",
                    " ",
                ).title()
            )
    return out


def _mask(value: str) -> str:
    """Mask a secret value, keeping first 4 chars visible."""
    if not value:
        return "(empty)"
    if len(value) <= 4:
        return "****"
    return value[:4] + "****"


# ── Catalog-driven interactive editor ────────────────────────


@dataclass(frozen=True, slots=True)
class ChannelEditorField:  # pylint: disable=too-many-instance-attributes
    """One setting exposed by the generic Channel editor."""

    name: str
    label: str
    kind: str = "text"
    required: bool = False
    secret: bool = False
    default: Any = None
    description: str = ""
    options: tuple[Any, ...] = ()


@dataclass(frozen=True, slots=True)
class ChannelEditorDefinition:
    """Runtime-neutral metadata used by the Console-style CLI editor."""

    key: str
    label: str
    fields: tuple[ChannelEditorField, ...]
    config_model: type[BaseModel] | None = None
    plugin_id: str | None = None


@dataclass(slots=True)
class EditableChannel:
    """One persisted or pending Channel instance in the CLI editor."""

    instance_id: str | None
    channel_type: str
    name: str
    enabled: bool = False
    settings: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ChannelEditorState:
    """Editable snapshot of one Agent's Channels and Console Transport."""

    channels: list[EditableChannel]
    console: ConsoleTransportConfig
    deleted_instance_ids: set[str] = field(default_factory=set)


def _model_editor_fields(
    model: type[BaseModel],
    *,
    include_enabled: bool = False,
) -> tuple[ChannelEditorField, ...]:
    """Derive CLI fields from the same Pydantic model used by the backend."""
    return _plugin_editor_fields(
        channel_config_fields_from_model(
            model,
            include_enabled=include_enabled,
        ),
    )


def _plugin_editor_fields(
    config_fields: list[dict[str, Any]],
) -> tuple[ChannelEditorField, ...]:
    """Normalize the existing plugin field protocol for the generic editor."""

    def editor_kind(item: dict[str, Any]) -> str:
        kind = str(item.get("schema_type") or item.get("type") or "text")
        if kind in {"array", "object"}:
            return "json"
        return kind

    return tuple(
        ChannelEditorField(
            name=str(item["name"]),
            label=str(item.get("label") or item["name"]),
            kind=editor_kind(item),
            required=bool(item.get("required", False)),
            secret=str(item.get("type") or "") == "password",
            default=item.get("default"),
            description=str(item.get("help") or ""),
            options=tuple(item.get("options") or ()),
        )
        for item in config_fields
    )


def get_channel_editor_definitions() -> dict[str, ChannelEditorDefinition]:
    """Return available external Channel definitions from one catalog view."""
    available = set(get_available_channels())
    definitions: dict[str, ChannelEditorDefinition] = {}
    for definition in sorted(
        BUILTIN_CHANNEL_CATALOG,
        key=lambda item: item.order,
    ):
        if definition.surface != "channel" or definition.key not in available:
            continue
        model = get_channel_config_model(definition.key)
        if model is None:
            continue
        definitions[definition.key] = ChannelEditorDefinition(
            key=definition.key,
            label=definition.label or definition.key.title(),
            fields=_model_editor_fields(model),
            config_model=model,
        )

    from ..plugins.registry import PluginRegistry

    for key, registration in (
        PluginRegistry().get_registered_channels().items()
    ):
        if key not in available:
            continue
        config_model = getattr(registration, "config_model", None)
        fields = (
            _model_editor_fields(config_model)
            if config_model is not None
            else _plugin_editor_fields(registration.config_fields)
        )
        definitions[key] = ChannelEditorDefinition(
            key=key,
            label=registration.label or key.title(),
            fields=fields,
            config_model=config_model,
            plugin_id=registration.plugin_id,
        )
    return definitions


def get_console_editor_definition() -> ChannelEditorDefinition:
    """Return the Console Transport editor outside the Channel catalog."""
    return ChannelEditorDefinition(
        key="console",
        label="Console",
        fields=_model_editor_fields(ConsoleTransportConfig),
        config_model=ConsoleTransportConfig,
    )


def _display_setting(field_spec: ChannelEditorField, value: Any) -> str:
    if value in (None, ""):
        return "(empty)"
    if field_spec.secret:
        return _mask(str(value))
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _prompt_json(label: str, current: Any) -> Any:
    default = json.dumps(
        current if current is not None else {},
        ensure_ascii=False,
    )
    while True:
        value = click.prompt(label, default=default, type=str)
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            click.echo(f"Invalid JSON: {exc}", err=True)


def _prompt_setting(
    field_spec: ChannelEditorField,
    current: Any,
) -> Any:
    """Prompt one setting using its schema-derived type."""
    default = current
    if default is None:
        default = field_spec.default
    if field_spec.kind in {"switch", "boolean"}:
        return prompt_confirm(
            field_spec.label,
            default=bool(default),
        )
    if field_spec.kind in {"select"} and field_spec.options:
        return prompt_select(
            field_spec.label,
            options=[(str(option), option) for option in field_spec.options],
        )
    if field_spec.kind in {"integer", "number"}:
        prompt_type = int if field_spec.kind == "integer" else float
        return click.prompt(
            field_spec.label,
            default=default if default is not None else 0,
            type=prompt_type,
        )
    if field_spec.kind == "json":
        return _prompt_json(field_spec.label, default)

    value = click.prompt(
        field_spec.label,
        default="" if default is None else str(default),
        hide_input=field_spec.secret,
        type=str,
    )
    if value == "" and field_spec.required:
        raise click.UsageError(f"{field_spec.label} is required")
    return value


def _edit_channel_interactive(
    channel: EditableChannel,
    definition: ChannelEditorDefinition,
) -> str:
    """Edit or delete one Channel instance. Return the chosen action."""
    fields_by_name = {item.name: item for item in definition.fields}
    while True:
        choices = [
            (f"Name: {channel.name}", "__name__"),
            (
                f"Enabled: {'yes' if channel.enabled else 'no'}",
                "__enabled__",
            ),
        ]
        for field_spec in definition.fields:
            current = channel.settings.get(
                field_spec.name,
                field_spec.default,
            )
            choices.append(
                (
                    f"{field_spec.label}: "
                    f"{_display_setting(field_spec, current)}",
                    field_spec.name,
                ),
            )
        choices.extend(
            [
                ("Delete instance", "__delete__"),
                ("Back", "__back__"),
            ],
        )
        choice = prompt_select(
            f"Configure {definition.label} ({channel.name})",
            options=choices,
        )
        if choice in (None, "__back__"):
            return "save"
        if choice == "__delete__":
            return "delete"
        if choice == "__name__":
            channel.name = click.prompt(
                "Instance name",
                default=channel.name,
                type=str,
            )
            continue
        if choice == "__enabled__":
            channel.enabled = prompt_confirm(
                "Enable this instance?",
                default=channel.enabled,
            )
            continue
        field_spec = fields_by_name[choice]
        channel.settings[choice] = _prompt_setting(
            field_spec,
            channel.settings.get(choice),
        )


def _edit_console_interactive(
    console: ConsoleTransportConfig,
) -> None:
    definition = get_console_editor_definition()
    values = console.model_dump(mode="json")
    enabled = bool(values.pop("enabled", True))
    editable = EditableChannel(
        instance_id="console",
        channel_type="console",
        name="Console",
        enabled=enabled,
        settings=values,
    )
    action = _edit_channel_interactive(editable, definition)
    if action == "delete":
        click.echo("Console Transport cannot be deleted.", err=True)
        return
    payload = {**editable.settings, "enabled": editable.enabled}
    updated = ConsoleTransportConfig.model_validate(payload)
    for name in updated.model_fields:
        setattr(console, name, getattr(updated, name))


def _default_settings(
    definition: ChannelEditorDefinition,
) -> dict[str, Any]:
    """Return plugin defaults without persisting every built-in default."""
    if definition.config_model is not None:
        return {}
    return {
        item.name: item.default
        for item in definition.fields
        if item.default is not None
    }


def configure_channels_interactive(  # pylint: disable=too-many-branches
    state: ChannelEditorState,
) -> None:
    """Edit all Channel instances through Catalog-derived definitions."""
    definitions = get_channel_editor_definitions()
    while True:
        choices: list[tuple[str, str]] = []
        for index, channel in enumerate(state.channels):
            status = "✓" if channel.enabled else "✗"
            label = definitions.get(channel.channel_type)
            type_label = label.label if label else channel.channel_type
            instance = channel.instance_id or "new"
            choices.append(
                (
                    f"{channel.name} ({type_label}, {instance}) [{status}]",
                    f"instance:{index}",
                ),
            )
        choices.extend(
            [
                ("Add Channel instance", "__add__"),
                (
                    "Configure Console Transport "
                    f"[{'✓' if state.console.enabled else '✗'}]",
                    "__console__",
                ),
                ("Save and exit", "__exit__"),
            ],
        )
        choice = prompt_select(
            "Select a Channel instance:",
            options=choices,
        )
        if choice is None:
            click.echo("\nOperation cancelled.")
            return
        if choice == "__exit__":
            return
        if choice == "__console__":
            _edit_console_interactive(state.console)
            continue
        if choice == "__add__":
            if not definitions:
                click.echo("No Channel types are available.", err=True)
                continue
            channel_type = prompt_select(
                "Select Channel type:",
                options=[
                    (item.label, item.key) for item in definitions.values()
                ],
            )
            if channel_type is None:
                continue
            definition = definitions[channel_type]
            item = EditableChannel(
                instance_id=None,
                channel_type=channel_type,
                name=click.prompt(
                    "Instance name",
                    default=definition.label,
                    type=str,
                ),
                settings=_default_settings(definition),
            )
            state.channels.append(item)
            if _edit_channel_interactive(item, definition) == "delete":
                state.channels.remove(item)
            continue

        index = int(choice.split(":", 1)[1])
        channel = state.channels[index]
        definition = definitions.get(channel.channel_type)
        if definition is None:
            click.echo(
                f"Channel type '{channel.channel_type}' is unavailable; "
                "its configuration was preserved.",
                err=True,
            )
            continue
        action = _edit_channel_interactive(channel, definition)
        if action != "delete":
            continue
        if channel.instance_id == channel.channel_type and any(
            item is not channel and item.channel_type == channel.channel_type
            for item in state.channels
        ):
            click.echo(
                "Delete secondary instances before the primary instance.",
                err=True,
            )
            continue
        if channel.instance_id is not None:
            state.deleted_instance_ids.add(channel.instance_id)
        state.channels.remove(channel)


def load_editable_channel_configs(
    root_config: Config,
    agent_config: AgentProfileConfig,
    agent_id: str,
) -> ChannelEditorState:
    """Build the CLI editor view from authoritative storage."""
    del root_config, agent_id
    return ChannelEditorState(
        channels=[
            EditableChannel(
                instance_id=instance_id,
                channel_type=channel.type,
                name=channel.name,
                enabled=channel.enabled,
                settings=dict(channel.settings),
            )
            for instance_id, channel in agent_config.channels.items()
        ],
        console=agent_config.transports.console.model_copy(deep=True),
    )


def persist_editable_channel_configs(
    root_config: Config,
    agent_config: AgentProfileConfig,
    agent_id: str,
    channel_configs: ChannelEditorState,
) -> None:
    """Persist instance-addressed CLI edits through ChannelConfigService."""
    del root_config
    service = ChannelConfigService(agent_config)
    agent_config.transports.console = ConsoleTransportConfig.model_validate(
        channel_configs.console.model_dump(mode="json"),
    )

    deleted = sorted(
        channel_configs.deleted_instance_ids,
        key=lambda instance_id: (
            instance_id
            == getattr(agent_config.channels.get(instance_id), "type", None)
        ),
    )
    for instance_id in deleted:
        if service.get(instance_id) is not None:
            service.delete(instance_id)

    for item in channel_configs.channels:
        value = {
            "name": item.name,
            "enabled": item.enabled,
            "settings": dict(item.settings),
        }
        if item.instance_id is None:
            service.create(item.channel_type, value)
        else:
            service.update(item.instance_id, value)
    save_agent_config(agent_id, agent_config)


# ── CLI commands ───────────────────────────────────────────────────


@click.group("channels")
def channels_group() -> None:
    """Manage Agent-owned Channel instances."""


def _channel_config_fields(ch):
    """Yield (field_name, value) for a channel config (model or dict)."""
    model_fields = getattr(type(ch), "model_fields", None)
    if model_fields is not None:
        for fn in model_fields:
            if fn == "enabled":
                continue
            yield (fn, getattr(ch, fn))
    elif isinstance(ch, dict):
        for k, v in ch.items():
            if k == "enabled":
                continue
            yield (k, v)
    elif hasattr(ch, "__dict__"):
        for k, v in vars(ch).items():
            if k == "enabled":
                continue
            yield (k, v)


def _channel_enabled(ch) -> bool:
    """Whether channel config has enabled=True."""
    if ch is None:
        return False
    if hasattr(ch, "enabled"):
        return bool(ch.enabled)
    if isinstance(ch, dict):
        return bool(ch.get("enabled", False))
    return False


@channels_group.command("list")
@click.option(
    "--agent-id",
    default="default",
    help="Agent ID (defaults to 'default')",
)
def list_cmd(agent_id: str) -> None:
    """Show current channel configuration."""
    try:
        agent_config = load_agent_config(agent_id)
        click.echo(f"Channels for agent: {agent_id}\n")
        channel_names = _get_channel_names()
        entries = [
            (
                "console",
                "console",
                "Console",
                agent_config.transports.console,
            ),
            *[
                (
                    instance_id,
                    channel.type,
                    channel.name,
                    {
                        **channel.settings,
                        "enabled": channel.enabled,
                    },
                )
                for instance_id, channel in agent_config.channels.items()
            ],
        ]
        for instance_id, channel_type, display_name, ch in entries:
            type_name = channel_names.get(channel_type, channel_type)
            status = (
                click.style("enabled", fg="green")
                if _channel_enabled(ch)
                else click.style("disabled", fg="red")
            )
            click.echo(f"\n{'─' * 40}")
            click.echo(
                f"  {display_name} ({type_name}, {instance_id})  "
                f"[{status}]",
            )
            click.echo(f"{'─' * 40}")

            for field_name, value in _channel_config_fields(ch):
                display = (
                    _mask(str(value))
                    if is_channel_secret_field(field_name)
                    else value
                )
                click.echo(f"  {field_name:20s}: {display}")

        click.echo()
    except (ValueError, AppBaseException) as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1) from e


@channels_group.command("config")
@click.option(
    "--agent-id",
    default="default",
    help="Agent ID (defaults to 'default')",
)
def configure_cmd(agent_id: str) -> None:
    """Interactively configure channels."""
    try:
        root_config = load_config()
        agent_config = load_agent_config(agent_id)
        click.echo(f"Configuring channels for agent: {agent_id}\n")

        channel_configs = load_editable_channel_configs(
            root_config,
            agent_config,
            agent_id,
        )
        configure_channels_interactive(channel_configs)
        persist_editable_channel_configs(
            root_config,
            agent_config,
            agent_id,
            channel_configs,
        )
        click.echo(f"\n✓ Configuration saved for agent {agent_id}")
    except (ValueError, AppBaseException) as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1) from e


@channels_group.command("send")
@click.option(
    "--agent-id",
    required=True,
    help="Agent ID sending the message",
)
@click.option(
    "--channel",
    required=True,
    help=(
        "Target channel (e.g., console, dingtalk, feishu, discord, "
        "imessage, qq)"
    ),
)
@click.option(
    "--target-user",
    required=True,
    help=("Target user ID (REQUIRED, get from 'qwenpaw chats list' query)"),
)
@click.option(
    "--target-session",
    required=True,
    help=("Target session ID (REQUIRED, get from 'qwenpaw chats list' query)"),
)
@click.option(
    "--text",
    required=True,
    help="Text message to send",
)
@click.option(
    "--base-url",
    default=None,
    help="Override the API base URL. Defaults to global --host/--port.",
)
@click.pass_context
def send_cmd(
    ctx: click.Context,
    agent_id: str,
    channel: str,
    target_user: str,
    target_session: str,
    text: str,
    base_url: Optional[str],
) -> None:
    """Send a text message to a channel.

    This command allows an agent to proactively send messages to users
    via configured channels (console, dingtalk, feishu, etc.).

    IMPORTANT: All 5 parameters are REQUIRED. You MUST query first to get
    valid target-user and target-session values.

    \b
    Complete Usage Flow:
      Step 1 - Query available sessions (REQUIRED):
        qwenpaw chats list --agent-id my_bot --channel console

      Step 2 - Extract parameters from query output:
        user_id: "alice"
        session_id: "alice_session_001"

      Step 3 - Send message using queried parameters:
        qwenpaw channels send --agent-id my_bot --channel console \\
          --target-user alice --target-session alice_session_001 \\
          --text "Hello!"

    \b
    Examples with jq automation:
      # Query and auto-extract parameters
      SESSIONS=$(qwenpaw chats list --agent-id bot --channel console)
      USER=$(echo "$SESSIONS" | jq -r '.[0].user_id')
      SESSION=$(echo "$SESSIONS" | jq -r '.[0].session_id')

      # Send message
      qwenpaw channels send --agent-id bot --channel console \\
        --target-user "$USER" --target-session "$SESSION" \\
        --text "Automated notification"

    \b
    Prerequisites:
      1. MUST use 'qwenpaw chats list' to get valid target-user and
         target-session
      2. Ensure the channel is properly configured
      3. All 5 parameters are required (no defaults)

    \b
    Returns:
      JSON response with success status and message details.
    """
    base_url = resolve_base_url(ctx, base_url)

    payload = {
        "channel": channel,
        "target_user": target_user,
        "target_session": target_session,
        "text": text,
    }

    with client(base_url) as c:
        headers = {"X-Agent-Id": agent_id}
        r = c.post("/messages/send", json=payload, headers=headers)
        r.raise_for_status()
        print_json(r.json())
