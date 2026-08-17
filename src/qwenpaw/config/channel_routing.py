# -*- coding: utf-8 -*-
"""Persistent configuration for Channel endpoints and agent bindings."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator


class ChannelEndpointConfig(BaseModel):
    """One external account whose credentials are agent-independent."""

    endpoint_id: str = Field(min_length=1)
    channel_key: str = Field(min_length=1)
    account_id: str = Field(min_length=1)
    enabled: bool = True
    settings: dict[str, Any] = Field(default_factory=dict)


class AgentBindingConfig(BaseModel):
    """Route one endpoint to one agent."""

    binding_id: str = Field(min_length=1)
    endpoint_id: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    enabled: bool = True
    priority: int = 0


class ChannelRoutingConfig(BaseModel):
    """Authoritative root-level Channel routing configuration."""

    endpoints: list[ChannelEndpointConfig] = Field(default_factory=list)
    bindings: list[AgentBindingConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_graph(self) -> "ChannelRoutingConfig":
        endpoint_ids = [item.endpoint_id for item in self.endpoints]
        duplicate_endpoints = _duplicates(endpoint_ids)
        if duplicate_endpoints:
            raise ValueError(
                f"Duplicate endpoint_id: {duplicate_endpoints[0]}",
            )

        binding_ids = [item.binding_id for item in self.bindings]
        duplicate_bindings = _duplicates(binding_ids)
        if duplicate_bindings:
            raise ValueError(
                f"Duplicate binding_id: {duplicate_bindings[0]}",
            )

        known = set(endpoint_ids)
        active_by_endpoint: dict[str, int] = {}
        for binding in self.bindings:
            if binding.endpoint_id not in known:
                raise ValueError(
                    f"Binding references unknown endpoint: "
                    f"{binding.endpoint_id}",
                )
            if binding.enabled:
                active_by_endpoint[binding.endpoint_id] = (
                    active_by_endpoint.get(binding.endpoint_id, 0) + 1
                )
        ambiguous = sorted(
            endpoint_id
            for endpoint_id, count in active_by_endpoint.items()
            if count > 1
        )
        if ambiguous:
            raise ValueError(
                f"Endpoint has multiple enabled bindings: {ambiguous[0]}",
            )
        return self


def _duplicates(values: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates)


__all__ = [
    "AgentBindingConfig",
    "ChannelEndpointConfig",
    "ChannelRoutingConfig",
]
