# -*- coding: utf-8 -*-
"""Compatibility conversion at the Runtime request boundary."""

from __future__ import annotations

from ..domain.turns.models import TurnRequest
from ..schemas import AgentRequest


def to_legacy_agent_request(request: TurnRequest) -> AgentRequest:
    """Adapt a core request for internal code not yet migrated."""
    channel = request.source.channel_type or request.source.kind
    legacy = AgentRequest(
        input=list(request.messages),
        session_id=request.session_id,
        user_id=request.user_id,
        agent_id=request.agent_id,
        channel=channel,
        request_context=dict(request.context),
    )
    legacy.id = request.turn_id
    legacy.channel_meta = {
        "channel_type": request.source.channel_type,
        "reply_target": request.reply_target,
    }
    return legacy


__all__ = ["to_legacy_agent_request"]
