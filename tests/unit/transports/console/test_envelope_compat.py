# -*- coding: utf-8 -*-
"""Compatibility contracts for the relocated Console envelope."""

from qwenpaw.runtime.envelope import Envelope as LegacyEnvelope
from qwenpaw.runtime.envelope import (
    _propagate_event_metadata as legacy_propagate_event_metadata,
)
from qwenpaw.transports.console.envelope import Envelope
from qwenpaw.transports.console.envelope import _propagate_event_metadata


def test_legacy_envelope_path_reexports_console_implementation() -> None:
    assert LegacyEnvelope is Envelope
    assert legacy_propagate_event_metadata is _propagate_event_metadata


def test_envelope_is_owned_by_console_transport() -> None:
    assert Envelope.__module__ == "qwenpaw.transports.console.envelope"
