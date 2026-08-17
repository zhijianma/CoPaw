# -*- coding: utf-8 -*-
"""Project legacy per-agent channel configs into endpoint bindings."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ...config.channel_routing import ChannelRoutingConfig
from ...domain.channels.models import AgentBinding, ChannelEndpoint


def _config_items(channels: Any) -> dict[str, Any]:
    if isinstance(channels, Mapping):
        return dict(channels)
    if hasattr(channels, "model_dump"):
        values = channels.model_dump()
        extras = getattr(channels, "__pydantic_extra__", None) or {}
        values.update(extras)
        return values
    return {}


def _settings(config: Any) -> dict[str, Any]:
    if isinstance(config, Mapping):
        return dict(config)
    if hasattr(config, "model_dump"):
        return config.model_dump()
    return {}


def project_agent_channels(
    agent_id: str,
    channels: Any,
) -> tuple[list[ChannelEndpoint], list[AgentBinding]]:
    """Create explicit compatibility routes for one legacy agent config."""
    if not str(agent_id or "").strip():
        raise ValueError("agent_id must not be empty")

    endpoints = []
    bindings = []
    for channel_key, config in _config_items(channels).items():
        settings = _settings(config)
        enabled = bool(settings.get("enabled", False))
        endpoint_id = f"{channel_key}:{agent_id}"
        endpoints.append(
            ChannelEndpoint(
                endpoint_id=endpoint_id,
                channel_key=channel_key,
                account_id=agent_id,
                enabled=enabled,
                settings=settings,
            ),
        )
        if enabled:
            bindings.append(
                AgentBinding(
                    binding_id=f"{endpoint_id}->{agent_id}",
                    endpoint_id=endpoint_id,
                    agent_id=agent_id,
                ),
            )
    return endpoints, bindings


def resolve_agent_channel_routes(
    agent_id: str,
    legacy_channels: Any,
    routing: ChannelRoutingConfig | None,
) -> tuple[list[ChannelEndpoint], list[AgentBinding]]:
    """Prefer explicit root routing and fall back to legacy ownership."""
    if routing is None or not (routing.endpoints or routing.bindings):
        return project_agent_channels(agent_id, legacy_channels)

    configured_bindings = [
        item for item in routing.bindings if item.agent_id == agent_id
    ]
    endpoint_ids = {item.endpoint_id for item in configured_bindings}
    configured_endpoints = [
        item for item in routing.endpoints if item.endpoint_id in endpoint_ids
    ]
    endpoints = [
        ChannelEndpoint(
            endpoint_id=item.endpoint_id,
            channel_key=item.channel_key,
            account_id=item.account_id,
            enabled=item.enabled,
            settings=item.settings,
        )
        for item in configured_endpoints
    ]
    bindings = [
        AgentBinding(
            binding_id=item.binding_id,
            endpoint_id=item.endpoint_id,
            agent_id=item.agent_id,
            enabled=item.enabled,
            priority=item.priority,
        )
        for item in configured_bindings
    ]
    return endpoints, bindings


__all__ = ["project_agent_channels", "resolve_agent_channel_routes"]
