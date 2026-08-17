# -*- coding: utf-8 -*-
"""Compatibility bridge from legacy Channel requests to core requests."""

from __future__ import annotations

import uuid
from typing import Any

from ..domain.channels.models import InboundMessage, ReplyTarget
from ..domain.channels.routing import BindingRouter, build_turn_request
from ..domain.turns.models import TurnRequest


class ChannelRequestBridge:
    """Normalize and route one request emitted by a legacy Channel."""

    def __init__(
        self,
        endpoint_id: str,
        router: BindingRouter,
    ) -> None:
        self._endpoint_id = endpoint_id
        self._router = router

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
                endpoint_id=self._endpoint_id,
                conversation_id=conversation_id,
                thread_id=metadata.get("thread_id"),
                metadata=metadata,
            )

        inbound = InboundMessage(
            message_id=str(
                getattr(request, "id", "") or uuid.uuid4().hex,
            ),
            endpoint_id=self._endpoint_id,
            sender_id=str(getattr(request, "user_id", "") or "anonymous"),
            conversation_id=conversation_id,
            content=tuple(getattr(request, "input", None) or ()),
            reply_target=reply_target,
            metadata=metadata,
        )
        route = self._router.resolve(
            self._endpoint_id,
            conversation_id=conversation_id,
            agent_hint=getattr(request, "agent_id", None),
        )
        return build_turn_request(
            inbound,
            route,
            turn_id=inbound.message_id,
            session_id=session_id or None,
        )


__all__ = ["ChannelRequestBridge"]
