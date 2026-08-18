# -*- coding: utf-8 -*-
"""Build core requests from Agent-owned Channel configurations."""

from __future__ import annotations

from ..turns.models import RequestSource, RequestSourceKind, TurnRequest
from .models import InboundMessage


def build_turn_request(
    inbound: InboundMessage,
    agent_id: str,
    *,
    turn_id: str,
    session_id: str | None = None,
    source_protocol: RequestSourceKind = "channel",
) -> TurnRequest:
    """Build a core request for the Channel configuration's owning Agent."""
    resolved_session_id = session_id or inbound.conversation_id
    return TurnRequest(
        turn_id=turn_id,
        agent_id=agent_id,
        session_id=resolved_session_id,
        user_id=inbound.sender_id,
        messages=inbound.content,
        source=RequestSource(
            protocol=source_protocol,
            channel_type=inbound.channel_type,
        ),
        reply_target=inbound.reply_target,
        context=inbound.metadata,
    )


__all__ = ["build_turn_request"]
