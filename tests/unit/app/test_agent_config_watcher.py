# -*- coding: utf-8 -*-
"""Tests for agent runtime configuration change detection."""

from qwenpaw.app.agent_config_watcher import _channel_runtime_hash
from qwenpaw.config.config import AgentProfileConfig


def test_channel_runtime_hash_tracks_channels_and_transports() -> None:
    baseline = AgentProfileConfig(id="sales", name="Sales")
    changed_channel = AgentProfileConfig(
        id="sales",
        name="Sales",
        channels={
            "telegram": {
                "type": "telegram",
                "name": "Main",
                "enabled": False,
                "settings": {},
            },
        },
    )
    changed_transport = baseline.model_copy(deep=True)
    changed_transport.transports.console.bot_prefix = "changed"

    baseline_hash = _channel_runtime_hash(
        baseline.channels,
        baseline.transports,
    )
    assert (
        _channel_runtime_hash(
            changed_channel.channels,
            changed_channel.transports,
        )
        != baseline_hash
    )
    assert (
        _channel_runtime_hash(
            changed_transport.channels,
            changed_transport.transports,
        )
        != baseline_hash
    )
