# -*- coding: utf-8 -*-
"""Built-in registry surface filtering contracts."""

from qwenpaw.app.channels.registry import get_channel_registry
from qwenpaw.transports.console.channel import ConsoleTransport


def test_web_registry_contains_only_console_transport() -> None:
    registry = get_channel_registry(surface="web")

    assert registry == {"console": ConsoleTransport}


def test_channel_registry_excludes_console_transport() -> None:
    registry = get_channel_registry(surface="channel")

    assert "console" not in registry
