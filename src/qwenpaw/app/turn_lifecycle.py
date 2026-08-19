# -*- coding: utf-8 -*-
"""Application services shared by Channel and Transport turn delivery."""

from __future__ import annotations

import importlib
import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def response_error_message(response: Any) -> str | None:
    """Extract a user-facing error from a canonical runtime response."""
    if not response:
        return None
    error_text = getattr(response, "error_text", None)
    if error_text:
        return str(error_text)
    value = response
    if getattr(response, "data", None) is not None:
        value = response.data
    elif getattr(response, "response", None) is not None:
        value = response.response
    error = getattr(value, "error", None)
    if not error:
        return None
    if hasattr(error, "message"):
        return getattr(error, "message", None) or str(error)
    if isinstance(error, dict):
        return error.get("message") or str(error)
    return str(error)


async def finish_response_cycle(workspace: Any, session_id: str) -> None:
    """Run best-effort browser cleanup after one response cycle."""
    workspace_dir = getattr(workspace, "workspace_dir", None)
    if not session_id or workspace_dir is None:
        return
    try:
        from ..browser.execution.kernel import get_default_kernel_manager
        from ..browser.tool_entrypoint import derive_workspace_id

        await get_default_kernel_manager().on_response_cycle_end(
            derive_workspace_id(Path(workspace_dir)),
            session_id,
        )
    except Exception:  # Provider cleanup must not fail a reply.
        logger.warning(
            "browser response-cycle cleanup failed for session=%s",
            session_id[:30],
            exc_info=True,
        )


def clear_session_turn_usage(session_id: str) -> None:
    """Drop staged per-session usage on turn start, cancel, or error."""
    if not session_id:
        return
    module = importlib.import_module("qwenpaw.token_usage.model_wrapper")
    module.TokenRecordingModelWrapper.pop_usage_for_session(session_id)


async def commit_turn_usage(
    *,
    workspace: Any,
    request: Any,
    session_id: str,
    default_channel: str,
    on_ready: Callable[[dict[str, Any] | None, dict[str, Any] | None], None],
    emit_sse: bool = True,
) -> list[str]:
    """Resolve, persist, and optionally encode per-turn token usage."""
    if not session_id:
        return []
    try:
        turn_usage = importlib.import_module("qwenpaw.token_usage.turn_usage")
        token_usage = importlib.import_module("qwenpaw.token_usage")
        session = getattr(workspace, "session", None)
        agent_id = getattr(workspace, "agent_id", "default")
        user_id = (
            getattr(request, "sender_id", "")
            or getattr(request, "user_id", "")
            or ""
        )
        source = getattr(request, "source", None)
        channel = (
            getattr(request, "channel_type", "")
            or getattr(source, "channel_type", "")
            or default_channel
        )
        turn, context, agent_state = await turn_usage.resolve_turn_usage(
            session_id=session_id,
            agent_id=agent_id,
            session=session,
            user_id=user_id,
            channel=channel,
        )
        if turn is None and context is None:
            return []
        on_ready(turn, context)
        if turn:
            logger.info("Usage for session %s: %s", session_id, turn)
        if session is not None:
            try:
                await token_usage.persist_turn_usage(
                    session=session,
                    session_id=session_id,
                    user_id=user_id,
                    channel=channel,
                    turn=turn,
                    ctx=context,
                    agent_state=agent_state,
                )
            except Exception:
                logger.warning("turn usage persist skipped", exc_info=True)
        if not emit_sse:
            return []
        payload = {
            "type": "turn_usage",
            "session_id": session_id,
            "usage": turn,
            "context_usage": context,
        }
        return [f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"]
    except Exception:
        logger.warning("turn usage commit skipped", exc_info=True)
        return []


__all__ = [
    "clear_session_turn_usage",
    "commit_turn_usage",
    "finish_response_cycle",
    "response_error_message",
]
