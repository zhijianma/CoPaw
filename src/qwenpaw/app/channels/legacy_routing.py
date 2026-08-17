# -*- coding: utf-8 -*-
"""Project legacy per-agent channel configs into endpoint bindings."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

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


__all__ = ["project_agent_channels"]
