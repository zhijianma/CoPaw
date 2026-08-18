# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Architecture guards for the Catalog-driven Channel CLI."""

from __future__ import annotations

import inspect
from types import SimpleNamespace

from pydantic import BaseModel

from qwenpaw.cli import channels_cmd
from qwenpaw.domain.channels.catalog import BUILTIN_CHANNEL_CATALOG
from qwenpaw.plugins.registry import PluginRegistry


class DemoPluginConfig(BaseModel):
    endpoint: str
    api_token: str = ""


class OptionalPluginConfig(BaseModel):
    retries: int | None = None
    tags: list[str] | None = None


def test_cli_has_no_hardcoded_builtin_configurator_registry() -> None:
    source = inspect.getsource(channels_cmd)

    assert "_ALL_CHANNEL_CONFIGURATORS" not in source
    assert "_SECRET_FIELDS" not in source
    assert "def configure_feishu(" not in source
    assert "def configure_telegram(" not in source


def test_cli_editor_definitions_cover_catalog(monkeypatch) -> None:
    external = {
        item.key
        for item in BUILTIN_CHANNEL_CATALOG
        if item.surface == "channel"
    }
    monkeypatch.setattr(
        channels_cmd,
        "get_available_channels",
        lambda: sorted(external),
    )

    definitions = channels_cmd.get_channel_editor_definitions()

    assert set(definitions) == external
    assert "app_id" in {field.name for field in definitions["feishu"].fields}
    assert "bot_token" in {
        field.name for field in definitions["telegram"].fields
    }


def test_console_is_a_separate_transport_editor() -> None:
    definitions = channels_cmd.get_channel_editor_definitions()

    assert "console" not in definitions
    assert channels_cmd.get_console_editor_definition().key == "console"


def test_plugin_config_model_drives_the_same_cli_editor(monkeypatch) -> None:
    registration = SimpleNamespace(
        config_model=DemoPluginConfig,
        config_fields=[],
        label="Demo",
        plugin_id="demo-plugin",
    )
    monkeypatch.setattr(
        channels_cmd,
        "get_available_channels",
        lambda: ["demo"],
    )
    monkeypatch.setattr(
        PluginRegistry,
        "get_registered_channels",
        lambda _self: {"demo": registration},
    )

    definition = channels_cmd.get_channel_editor_definitions()["demo"]

    assert definition.config_model is DemoPluginConfig
    assert [field.name for field in definition.fields] == [
        "endpoint",
        "api_token",
    ]
    assert definition.fields[1].secret is True


def test_optional_schema_types_keep_numeric_and_json_editors() -> None:
    fields = {
        field.name: field
        for field in channels_cmd._model_editor_fields(
            OptionalPluginConfig,
        )
    }

    assert fields["retries"].kind == "integer"
    assert fields["tags"].kind == "json"
