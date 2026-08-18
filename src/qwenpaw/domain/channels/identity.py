# -*- coding: utf-8 -*-
"""Stable identity rules for agent-owned Channel instances."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ChannelIdentity:
    """Separate a Channel adapter type from its persisted instance ID."""

    instance_id: str
    channel_type: str

    def __post_init__(self) -> None:
        if not self.instance_id:
            raise ValueError("instance_id must not be empty")
        if not self.channel_type:
            raise ValueError("channel_type must not be empty")

    @property
    def is_primary(self) -> bool:
        """Return whether this instance uses all legacy identities."""
        return self.instance_id == self.channel_type

    def runtime_session_id(self, platform_session_id: str) -> str:
        """Qualify only secondary instance sessions."""
        if self.is_primary:
            return platform_session_id
        prefix = f"{self.instance_id}:"
        if platform_session_id.startswith(prefix):
            return platform_session_id
        return f"{prefix}{platform_session_id}"

    def platform_session_id(self, runtime_session_id: str) -> str:
        """Remove this secondary instance's runtime qualifier."""
        if self.is_primary:
            return runtime_session_id
        prefix = f"{self.instance_id}:"
        if runtime_session_id.startswith(prefix):
            return runtime_session_id[len(prefix) :]
        return runtime_session_id

    def state_dir(self, workspace_dir: Path) -> Path:
        """Return the compatible primary or isolated secondary state dir."""
        if self.is_primary:
            return workspace_dir
        digest = hashlib.sha256(
            self.instance_id.encode("utf-8"),
        ).hexdigest()[:16]
        return workspace_dir / ".channel_instances" / digest


__all__ = ["ChannelIdentity"]
