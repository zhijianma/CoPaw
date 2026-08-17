# -*- coding: utf-8 -*-
"""Compatibility channel type identifiers."""
from __future__ import annotations

from ...domain.channels.catalog import BUILTIN_CHANNEL_KEYS


# Built-in channel type identifiers. Plugin channels use arbitrary str keys.
BUILTIN_CHANNEL_TYPES = BUILTIN_CHANNEL_KEYS

# ChannelType is str to allow plugin channels; built-in set above.
ChannelType = str

# Default channel when none is specified (runner / config).
DEFAULT_CHANNEL: ChannelType = "console"
