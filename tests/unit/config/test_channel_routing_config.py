# -*- coding: utf-8 -*-
"""Tests for explicit endpoint and agent binding configuration."""

import pytest
from pydantic import ValidationError

from qwenpaw.config.channel_routing import (
    AgentBindingConfig,
    ChannelEndpointConfig,
    ChannelRoutingConfig,
)
from qwenpaw.config.config import Config


def _endpoint() -> ChannelEndpointConfig:
    return ChannelEndpointConfig(
        endpoint_id="telegram:corp",
        channel_key="telegram",
        account_id="corp",
        settings={"bot_token": "secret"},
    )


def _binding() -> AgentBindingConfig:
    return AgentBindingConfig(
        binding_id="telegram:corp->sales",
        endpoint_id="telegram:corp",
        agent_id="sales",
    )


def test_root_config_accepts_explicit_channel_routing() -> None:
    config = Config(
        channel_routing=ChannelRoutingConfig(
            endpoints=[_endpoint()],
            bindings=[_binding()],
        ),
    )

    assert config.channel_routing.endpoints[0].account_id == "corp"
    assert config.channel_routing.bindings[0].agent_id == "sales"


def test_channel_routing_rejects_dangling_binding() -> None:
    with pytest.raises(ValidationError, match="unknown endpoint"):
        ChannelRoutingConfig(bindings=[_binding()])


def test_channel_routing_rejects_duplicate_ids() -> None:
    with pytest.raises(ValidationError, match="Duplicate endpoint_id"):
        ChannelRoutingConfig(endpoints=[_endpoint(), _endpoint()])


def test_channel_routing_rejects_ambiguous_active_binding() -> None:
    second = AgentBindingConfig(
        binding_id="telegram:corp->support",
        endpoint_id="telegram:corp",
        agent_id="support",
    )

    with pytest.raises(ValidationError, match="multiple enabled bindings"):
        ChannelRoutingConfig(
            endpoints=[_endpoint()],
            bindings=[_binding(), second],
        )
