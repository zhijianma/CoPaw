# -*- coding: utf-8 -*-
"""Application service for agent-owned Channel configurations."""

from __future__ import annotations

import uuid
from typing import Any

from ...config.config import AgentChannelConfig, AgentProfileConfig


class ChannelConfigService:
    """Manage stable Channel instances owned by one Agent."""

    def __init__(self, agent: AgentProfileConfig) -> None:
        self._agent = agent

    def list(self) -> list[tuple[str, AgentChannelConfig]]:
        """Return Channel configurations in persisted order."""
        return list(self._agent.channels.items())

    def get(self, instance_id: str) -> AgentChannelConfig | None:
        """Return one configuration by stable instance ID."""
        return self._agent.channels.get(instance_id)

    def create(
        self,
        channel_type: str,
        value: dict[str, Any],
    ) -> tuple[str, AgentChannelConfig]:
        """Create a primary-compatible or generated secondary instance."""
        instance_id = self._new_instance_id(channel_type)
        channel = self._validate(channel_type, value)
        self._agent.channels[instance_id] = channel
        return instance_id, channel

    def update(
        self,
        instance_id: str,
        value: dict[str, Any],
    ) -> AgentChannelConfig:
        """Replace one configuration without changing its identity."""
        current = self.get(instance_id)
        if current is None:
            raise KeyError(instance_id)
        requested_type = str(value.get("type") or current.type)
        if requested_type != current.type:
            raise ValueError("Channel type cannot be changed")
        channel = self._validate(current.type, value)
        self._agent.channels[instance_id] = channel
        return channel

    def delete(self, instance_id: str) -> AgentChannelConfig:
        """Remove one instance without implicitly promoting another."""
        channel = self.get(instance_id)
        if channel is None:
            raise KeyError(instance_id)
        if instance_id == channel.type and any(
            key != instance_id and value.type == channel.type
            for key, value in self._agent.channels.items()
        ):
            raise ValueError(
                f"Cannot delete primary Channel while secondary instances "
                f"exist: {instance_id}",
            )
        try:
            return self._agent.channels.pop(instance_id)
        except KeyError:
            raise KeyError(instance_id) from None

    def _new_instance_id(self, channel_type: str) -> str:
        if self.get(channel_type) is None:
            return channel_type
        while True:
            instance_id = f"{channel_type}-{uuid.uuid4().hex[:8]}"
            if self.get(instance_id) is None:
                return instance_id

    @staticmethod
    def _validate(
        channel_type: str,
        value: dict[str, Any],
    ) -> AgentChannelConfig:
        payload = dict(value)
        payload["type"] = channel_type
        channel = AgentChannelConfig.model_validate(payload)
        channel.validate_for_type(channel_type)
        return channel


__all__ = ["ChannelConfigService"]
