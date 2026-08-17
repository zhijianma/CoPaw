# -*- coding: utf-8 -*-
"""Application service for agent-owned Channel configurations."""

from __future__ import annotations

from typing import Any

from ...config.config import AgentChannelConfig, AgentProfileConfig


class ChannelConfigService:
    """Manage the single configuration for each Channel type."""

    def __init__(self, agent: AgentProfileConfig) -> None:
        self._agent = agent

    def list(self) -> list[tuple[str, AgentChannelConfig]]:
        """Return Channel configurations in persisted order."""
        return list(self._agent.channels.items())

    def get(self, channel_type: str) -> AgentChannelConfig | None:
        """Return the configuration for a Channel type."""
        return self._agent.channels.get(channel_type)

    def create(
        self,
        channel_type: str,
        value: dict[str, Any],
    ) -> AgentChannelConfig:
        """Create the only configuration for a Channel type."""
        if self.get(channel_type) is not None:
            raise ValueError(
                f"Channel type is already configured: {channel_type}",
            )
        channel = self._validate(channel_type, value)
        self._agent.channels[channel_type] = channel
        return channel

    def update(
        self,
        channel_type: str,
        value: dict[str, Any],
    ) -> AgentChannelConfig:
        """Replace the configuration for a Channel type."""
        if self.get(channel_type) is None:
            raise KeyError(channel_type)
        channel = self._validate(channel_type, value)
        self._agent.channels[channel_type] = channel
        return channel

    def delete(self, channel_type: str) -> AgentChannelConfig:
        """Remove and return the configuration for a Channel type."""
        try:
            return self._agent.channels.pop(channel_type)
        except KeyError:
            raise KeyError(channel_type) from None

    @staticmethod
    def _validate(
        channel_type: str,
        value: dict[str, Any],
    ) -> AgentChannelConfig:
        channel = AgentChannelConfig.model_validate(value)
        channel.validate_for_type(channel_type)
        return channel


__all__ = ["ChannelConfigService"]
