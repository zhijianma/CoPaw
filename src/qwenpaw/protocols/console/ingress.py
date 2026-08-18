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
        if isinstance(request, dict) and "content_parts" in request:
            return self._decode_native_payload(request)
        if isinstance(request, dict):
            from ...schemas import AgentRequest

            request = AgentRequest(**request)

        session_id = str(
            getattr(request, "session_id", "") or uuid.uuid4().hex,
        )
        turn_id = str(getattr(request, "id", "") or uuid.uuid4().hex)
        agent_id = str(
            getattr(request, "agent_id", "") or self._default_agent_id,
        )
        channel_type = str(getattr(request, "channel", "") or "console")
        channel_meta = dict(getattr(request, "channel_meta", None) or {})
        context = dict(getattr(request, "request_context", None) or {})
        model_slot_override = getattr(request, "model_slot_override", None)
        if model_slot_override is not None:
            context["model_slot_override"] = model_slot_override
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
            context=context,
        )

    def _decode_native_payload(self, payload: dict[str, Any]) -> TurnRequest:
        """Decode the Console router's normalized native payload."""
        from ...schemas import Message, Role

        meta = dict(payload.get("meta") or {})
        session_id = str(
            meta.get("session_id")
            or payload.get("session_id")
            or uuid.uuid4().hex,
        )
        user_id = str(
            payload.get("sender_id") or meta.get("user_id") or session_id,
        )
        context = dict(meta.get("request_context") or {})
        model_slot_override = payload.get("model_slot_override")
        if model_slot_override is not None:
            context["model_slot_override"] = model_slot_override
        content = list(payload.get("content_parts") or [])
        message_metadata = dict(payload.get("message_metadata") or {})
        return TurnRequest(
            turn_id=str(payload.get("message_id") or uuid.uuid4().hex),
            agent_id=self._default_agent_id,
            session_id=session_id,
            user_id=user_id,
            messages=(
                Message(
                    role=Role.USER,
                    content=content,
                    metadata=message_metadata,
                ),
            ),
            source=RequestSource(
                protocol="console",
                endpoint_id=meta.get("channel_instance_id"),
                channel_type=str(payload.get("channel_id") or "console"),
            ),
            context=context,
        )


__all__ = ["ConsoleTurnIngress"]
