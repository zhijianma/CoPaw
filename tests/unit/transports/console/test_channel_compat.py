# -*- coding: utf-8 -*-
"""Compatibility contracts for the relocated Console transport."""

from qwenpaw.app.channels.console.channel import ConsoleChannel
from qwenpaw.transports.console.channel import ConsoleTransport


def test_legacy_console_channel_is_transport_alias() -> None:
    assert ConsoleChannel is ConsoleTransport
    assert ConsoleTransport.__module__ == "qwenpaw.transports.console.channel"
