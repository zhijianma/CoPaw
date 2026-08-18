# -*- coding: utf-8 -*-
"""Decode the existing Console API schema into the core request model."""

from __future__ import annotations

import uuid
from typing import Any

from ...domain.turns.models import RequestSource, TurnRequest


class ConsoleTurnIngress:
    """Preserve the public AgentRequest schema at the Protocol edge."""

    def __init__(self, *, default_agent_id: str = "default") -> None:
        self._default_agent_id = default_agent_id

    def decode(self, request: Any) -> TurnRequest:
        """Decode an AgentRequest instance or its dictionary form."""
        if isinstance(request, dict):
            from ...schemas import AgentRequest

            request = AgentRequest(**request)

        session_id = str(
            getattr(request, "session_id", "") or uuid.uuid4().hex
        )
        turn_id = str(getattr(request, "id", "") or uuid.uuid4().hex)
        agent_id = str(
            getattr(request, "agent_id", "") or self._default_agent_id,
        )
        channel_type = str(getattr(request, "channel", "") or "console")
        channel_meta = dict(getattr(request, "channel_meta", None) or {})
        return TurnRequest(
            turn_id=turn_id,
            agent_id=agent_id,
            session_id=session_id,
            user_id=str(getattr(request, "user_id", "") or session_id),
            messages=getattr(request, "input", None) or (),
            source=RequestSource(
                protocol="console",
                endpoint_id=channel_meta.get("channel_instance_id"),
                channel_type=channel_type,
            ),
            reply_target=channel_meta.get("reply_target"),
            context=dict(getattr(request, "request_context", None) or {}),
        )


__all__ = ["ConsoleTurnIngress"]
