# -*- coding: utf-8 -*-
"""Application model for one Channel-owned turn."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Sequence

from ...domain.channels.models import InboundMessage, ReplyTarget
from ...domain.channels.routing import build_turn_request
from ...domain.turns.models import TurnRequest


@dataclass(slots=True)
class ChannelTurn:
    """Normalized inbound data plus Channel-local per-turn state.

    ``InboundMessage`` remains the immutable domain fact.  This application
    model adds the resolved session and mutable adapter state needed while a
    platform reply is being streamed, without leaking either into Runtime.
    """

    session_id: str
    sender_id: str
    messages: Sequence[Any]
    channel_type: str
    metadata: dict[str, Any] = field(default_factory=dict)
    message_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    state: dict[str, Any] = field(default_factory=dict)

    def to_request(
        self,
        *,
        agent_id: str,
        instance_id: str,
        runtime_session_id: str,
        channel_instance: Any,
    ) -> TurnRequest:
        """Create the only request shape accepted by the runtime core."""
        metadata = dict(self.metadata)
        metadata["channel_instance_id"] = instance_id
        metadata["_channel_instance"] = channel_instance
        conversation_id = str(
            metadata.get("conversation_id") or self.session_id,
        )
        target = metadata.get("reply_target")
        if not isinstance(target, ReplyTarget):
            target = ReplyTarget(
                channel_type=self.channel_type,
                conversation_id=conversation_id,
                thread_id=metadata.get("thread_id"),
                metadata=metadata,
            )
        inbound = InboundMessage(
            message_id=self.message_id,
            channel_type=self.channel_type,
            sender_id=self.sender_id or "anonymous",
            conversation_id=conversation_id,
            content=self.messages,
            reply_target=target,
            metadata=metadata,
        )
        return build_turn_request(
            inbound,
            agent_id,
            turn_id=self.message_id,
            session_id=runtime_session_id,
        )


__all__ = ["ChannelTurn"]
