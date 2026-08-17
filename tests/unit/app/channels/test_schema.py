# -*- coding: utf-8 -*-
"""Unit tests for qwenpaw.app.channels.schema."""

from __future__ import annotations

# pylint: disable=protected-access,redefined-outer-name,unused-argument

from qwenpaw.app.channels.schema import (
    BUILTIN_CHANNEL_TYPES,
    DEFAULT_CHANNEL,
    ChannelType,
)
from qwenpaw.domain.channels.catalog import BUILTIN_CHANNEL_KEYS


class TestChannelSchemaConstants:
    def test_default_channel_is_console(self):
        assert DEFAULT_CHANNEL == "console"

    def test_default_channel_is_builtin(self):
        assert DEFAULT_CHANNEL in BUILTIN_CHANNEL_TYPES

    def test_channel_type_is_str(self):
        assert ChannelType is str

    def test_builtin_types_contains_expected(self):
        for name in (
            "imessage",
            "discord",
            "dingtalk",
            "feishu",
            "qq",
            "telegram",
            "mqtt",
            "console",
            "voice",
            "sip",
            "slack",
            "xiaoyi",
            "yuanbao",
        ):
            assert name in BUILTIN_CHANNEL_TYPES

    def test_builtin_types_is_tuple(self):
        assert isinstance(BUILTIN_CHANNEL_TYPES, tuple)

    def test_builtin_types_unique(self):
        assert len(BUILTIN_CHANNEL_TYPES) == len(set(BUILTIN_CHANNEL_TYPES))

    def test_builtin_types_are_derived_from_catalog(self):
        assert BUILTIN_CHANNEL_TYPES == BUILTIN_CHANNEL_KEYS
