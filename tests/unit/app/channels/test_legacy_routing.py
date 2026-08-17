# -*- coding: utf-8 -*-
"""Legacy per-agent channel configuration routing projection tests."""

from qwenpaw.app.channels.legacy_routing import (
    project_agent_channels,
    resolve_agent_channel_routes,
)
from qwenpaw.app.channels.manager import ChannelManager
from qwenpaw.config.channel_routing import (
    AgentBindingConfig,
    ChannelEndpointConfig,
    ChannelRoutingConfig,
)
from qwenpaw.config.config import ChannelConfig, TelegramConfig
from qwenpaw.domain.turns.models import TurnRequest
from qwenpaw.schemas import AgentRequest


class _Channel:
    channel = "telegram"

    def __init__(self) -> None:
        self.bridge = None

    def set_request_bridge(self, bridge: object) -> None:
        self.bridge = bridge


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


def test_channel_manager_injects_canonical_request_bridge() -> None:
    endpoints, bindings = project_agent_channels(
        "sales",
        ChannelConfig(
            telegram=TelegramConfig(enabled=True, bot_token="secret"),
        ),
    )
    channel = _Channel()

    ChannelManager(
        [channel],  # type: ignore[list-item]
        endpoints=endpoints,
        bindings=bindings,
    )

    assert channel.bridge is not None
    turn = channel.bridge.build(
        AgentRequest(
            session_id="telegram:chat-1",
            user_id="user-1",
            channel="telegram",
        ),
    )
    assert isinstance(turn, TurnRequest)
    assert turn.agent_id == "sales"


def test_explicit_routing_replaces_legacy_agent_ownership() -> None:
    routing = ChannelRoutingConfig(
        endpoints=[
            ChannelEndpointConfig(
                endpoint_id="telegram:corp",
                channel_key="telegram",
                account_id="corp",
                settings={"bot_token": "root-secret"},
            ),
        ],
        bindings=[
            AgentBindingConfig(
                binding_id="telegram:corp->sales",
                endpoint_id="telegram:corp",
                agent_id="sales",
            ),
        ],
    )
    legacy = ChannelConfig(
        telegram=TelegramConfig(enabled=True, bot_token="legacy-secret"),
    )

    endpoints, bindings = resolve_agent_channel_routes(
        "sales",
        legacy,
        routing,
    )

    assert [endpoint.endpoint_id for endpoint in endpoints] == [
        "telegram:corp",
    ]
    assert endpoints[0].settings["bot_token"] == "root-secret"
    assert bindings[0].agent_id == "sales"


def test_empty_explicit_routing_falls_back_to_legacy_projection() -> None:
    endpoints, bindings = resolve_agent_channel_routes(
        "sales",
        ChannelConfig(
            telegram=TelegramConfig(enabled=True, bot_token="legacy"),
        ),
        ChannelRoutingConfig(),
    )

    assert any(
        endpoint.endpoint_id == "telegram:sales" for endpoint in endpoints
    )
    assert any(binding.agent_id == "sales" for binding in bindings)


def test_manager_injects_bridge_into_external_transport() -> None:
    endpoints, bindings = project_agent_channels(
        "sales",
        ChannelConfig(
            console={"enabled": True},
        ),
    )
    transport = _Channel()
    transport.channel = "console"

    ChannelManager(
        [],
        endpoints=endpoints,
        bindings=bindings,
        transports=[transport],  # type: ignore[list-item]
    )

    assert transport.bridge is not None
