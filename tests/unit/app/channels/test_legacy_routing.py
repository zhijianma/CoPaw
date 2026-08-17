# -*- coding: utf-8 -*-
"""Legacy per-agent channel configuration routing projection tests."""

from qwenpaw.app.channels.legacy_routing import project_agent_channels
from qwenpaw.app.channels.manager import ChannelManager
from qwenpaw.config.config import ChannelConfig, TelegramConfig


def test_project_agent_channels_creates_explicit_endpoint_and_binding() -> (
    None
):
    channels = ChannelConfig(
        telegram=TelegramConfig(enabled=True, bot_token="secret"),
    )

    endpoints, bindings = project_agent_channels("sales", channels)
    endpoint_by_key = {
        endpoint.channel_key: endpoint for endpoint in endpoints
    }

    telegram = endpoint_by_key["telegram"]
    assert telegram.endpoint_id == "telegram:sales"
    assert telegram.account_id == "sales"
    assert telegram.enabled is True
    assert telegram.settings["bot_token"] == "secret"
    assert any(
        binding.endpoint_id == telegram.endpoint_id
        and binding.agent_id == "sales"
        for binding in bindings
    )


def test_project_agent_channels_keeps_disabled_endpoint_without_binding() -> (
    None
):
    channels = ChannelConfig(
        telegram=TelegramConfig(enabled=False),
    )

    endpoints, bindings = project_agent_channels("sales", channels)
    telegram = next(
        endpoint
        for endpoint in endpoints
        if endpoint.channel_key == "telegram"
    )

    assert telegram.enabled is False
    assert all(
        binding.endpoint_id != telegram.endpoint_id for binding in bindings
    )


def test_channel_manager_exposes_explicit_route_resolution() -> None:
    endpoints, bindings = project_agent_channels(
        "sales",
        ChannelConfig(
            telegram=TelegramConfig(enabled=True, bot_token="secret"),
        ),
    )
    manager = ChannelManager(
        [],
        endpoints=endpoints,
        bindings=bindings,
    )

    route = manager.resolve_route(
        "telegram:sales",
        conversation_id="chat-1",
    )

    assert route.agent_id == "sales"
