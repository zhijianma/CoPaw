# -*- coding: utf-8 -*-
"""Compatibility bridge from legacy Channel requests to core requests."""

from __future__ import annotations

import uuid
from typing import Any

from ..domain.channels.models import InboundMessage, ReplyTarget
from ..domain.channels.routing import build_turn_request
from ..domain.turns.models import TurnRequest


class ChannelRequestBridge:
    """Normalize and route one request emitted by a legacy Channel."""

    def __init__(
        self,
        agent_id: str,
        channel_type: str,
    ) -> None:
        self._agent_id = agent_id
        self._channel_type = channel_type

    def build(self, request: Any) -> TurnRequest:
        """Build a transport-neutral request while preserving metadata."""
        metadata = dict(getattr(request, "channel_meta", None) or {})
        session_id = str(getattr(request, "session_id", "") or "")
        conversation_id = str(
            metadata.get("conversation_id") or session_id,
        )
        reply_target = metadata.get("reply_target")
        if not isinstance(reply_target, ReplyTarget):
            reply_target = ReplyTarget(
                channel_type=self._channel_type,
                conversation_id=conversation_id,
                thread_id=metadata.get("thread_id"),
                metadata=metadata,
            )

        inbound = InboundMessage(
            message_id=str(
                getattr(request, "id", "") or uuid.uuid4().hex,
            ),
            channel_type=self._channel_type,
            sender_id=str(getattr(request, "user_id", "") or "anonymous"),
            conversation_id=conversation_id,
            content=tuple(getattr(request, "input", None) or ()),
            reply_target=reply_target,
            metadata=metadata,
        )
        return build_turn_request(
            inbound,
            self._agent_id,
            turn_id=inbound.message_id,
        )


__all__ = ["ChannelRequestBridge"]
