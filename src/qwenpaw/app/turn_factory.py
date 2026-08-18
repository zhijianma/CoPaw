# -*- coding: utf-8 -*-
"""Application factories for protocol-neutral turn commands."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from ..domain.turns.models import RequestSource, TurnRequest
from ..schemas import Message, Role, TextContent


def coerce_turn_messages(value: Any) -> tuple[Any, ...]:
    """Validate application-owned message input without a protocol schema."""
    if value is None:
        return ()
    if isinstance(value, str):
        return (Message(role=Role.USER, content=[TextContent(text=value)]),)
    items = value if isinstance(value, Sequence) else (value,)
    result: list[Any] = []
    for item in items:
        if isinstance(item, Message):
            result.append(item)
        elif isinstance(item, dict):
            result.append(Message.model_validate(item))
        else:
            result.append(item)
    return tuple(result)


def create_turn_request(
    *,
    agent_id: str,
    session_id: str,
    user_id: str,
    protocol: str,
    messages: Any,
    channel_type: str | None = None,
    endpoint_id: str | None = None,
    context: dict[str, Any] | None = None,
    turn_id: str | None = None,
) -> TurnRequest:
    """Create the canonical command used by internal application sources."""
    return TurnRequest(
        turn_id=turn_id or uuid.uuid4().hex,
        agent_id=agent_id,
        session_id=session_id,
        user_id=user_id,
        messages=coerce_turn_messages(messages),
        source=RequestSource(
            protocol=protocol,
            endpoint_id=endpoint_id,
            channel_type=channel_type,
        ),
        context=context or {},
    )


def create_text_turn(
    *,
    agent_id: str,
    session_id: str,
    user_id: str,
    protocol: str,
    text: str,
    channel_type: str | None = None,
    context: dict[str, Any] | None = None,
) -> TurnRequest:
    """Create a canonical user-text turn for an internal source."""
    return create_turn_request(
        agent_id=agent_id,
        session_id=session_id,
        user_id=user_id,
        protocol=protocol,
        messages=[Message(role=Role.USER, content=[TextContent(text=text)])],
        channel_type=channel_type,
        context=context,
    )


__all__ = ["coerce_turn_messages", "create_text_turn", "create_turn_request"]
