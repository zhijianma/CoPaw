# -*- coding: utf-8 -*-
"""Built-in registry surface filtering contracts."""

from qwenpaw.app.channels.registry import get_channel_registry


def test_channel_registry_excludes_console_transport() -> None:
    registry = get_channel_registry()

    assert "console" not in registry
