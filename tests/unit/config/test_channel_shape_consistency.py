# -*- coding: utf-8 -*-
"""Consistency guards for the canonical built-in Channel catalog."""

# pylint: disable=protected-access
from __future__ import annotations

from qwenpaw.app.channels.registry import _BUILTIN_SPECS
from qwenpaw.app.routers.config import _channel_config_class
from qwenpaw.domain.channels.catalog import get_channel_config_model
from qwenpaw.config.config import AgentProfileConfig, Config
from qwenpaw.domain.channels.catalog import BUILTIN_CHANNEL_CATALOG


def test_catalog_is_the_source_for_builtin_specs() -> None:
    expected = {
        item.key: (item.module_name, item.class_name)
        for item in BUILTIN_CHANNEL_CATALOG
    }

    assert _BUILTIN_SPECS == expected


def test_catalog_resolves_every_builtin_config_model() -> None:
    for definition in BUILTIN_CHANNEL_CATALOG:
        model = get_channel_config_model(definition.key)

        assert model is not None
        assert model.__name__ == definition.config_class_name
        assert _channel_config_class(definition.key) is model


def test_plugin_channel_has_no_builtin_config_model() -> None:
    assert get_channel_config_model("some_plugin_channel") is None
    assert _channel_config_class("some_plugin_channel") is None


def test_channel_configs_are_owned_only_by_agent_profiles() -> None:
    assert "channels" not in Config.model_fields
    assert "channels" in AgentProfileConfig.model_fields
    assert AgentProfileConfig(id="default", name="Default").channels == {}
