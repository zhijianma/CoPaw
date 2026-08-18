# -*- coding: utf-8 -*-
"""Persist provider-neutral third-party turns in QwenPaw sessions."""

from __future__ import annotations

import json
import mimetypes
from pathlib import Path
from typing import Any

from agentscope.message import Msg
from agentscope.state import AgentState

from ..runtime._state_utils import StateProxy
from .events import (
    HarnessEvent,
    HarnessEventKind,
    HarnessHistoryItem,
    HarnessHistoryKind,
)


class HarnessSessionBridge:
    """Materialize third-party turns in the existing session format."""

    def __init__(self, session: Any) -> None:
        self._session = session

    async def has_history(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
    ) -> bool:
        """Return whether QwenPaw already has a materialized transcript."""
        persisted = await self._session.get_session_state_dict(
            session_id,
            user_id,
            channel,
        )
        state = (persisted.get("agent") or {}).get("state") or {}
        return bool(state.get("context"))

    async def hydrate(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
        backend: str,
        history: list[HarnessHistoryItem],
    ) -> None:
        """Save recovered provider history when no QwenPaw context exists."""
        if not history or await self.has_history(
            session_id=session_id,
            user_id=user_id,
            channel=channel,
        ):
            return
        state = AgentState().model_dump(mode="json")
        state["context"] = self._history_messages(history, backend)
        proxy = StateProxy()
        proxy.data = {"state": state}
        await self._session.save_session_state(
            session_id=session_id,
            user_id=user_id,
            channel=channel,
            agent=proxy,
        )

    async def append_turn(
        self,
        *,
        request: Any,
        events: list[HarnessEvent],
        backend: str,
    ) -> None:
        """Append one request and its normalized output atomically."""
        session_id = str(getattr(request, "session_id", "") or "default")
        user_id = str(request.user_id or session_id)
        channel = str(request.source.channel_type or "")
        persisted = await self._session.get_session_state_dict(
            session_id,
            user_id,
            channel,
        )
        agent = persisted.get("agent")
        agent_data = dict(agent) if isinstance(agent, dict) else {}
        state = agent_data.get("state")
        if not isinstance(state, dict):
            state = AgentState().model_dump(mode="json")
        context = state.get("context")
        if not isinstance(context, list):
            context = []
        context.extend(self._request_messages(request, backend))
        context.extend(self._event_messages(events, backend))
        state["context"] = context

        proxy = StateProxy()
        agent_data["state"] = state
        proxy.data = agent_data
        await self._session.save_session_state(
            session_id=session_id,
            user_id=user_id,
            channel=channel,
            agent=proxy,
        )

    async def clear(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
    ) -> None:
        """Replace a materialized third-party transcript with empty state."""
        proxy = StateProxy()
        proxy.data = {"state": AgentState().model_dump(mode="json")}
        await self._session.save_session_state(
            session_id=session_id,
            user_id=user_id,
            channel=channel,
            agent=proxy,
        )

    @classmethod
    def _request_messages(
        cls,
        request: Any,
        backend: str,
    ) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        for item in request.messages:
            role = cls._enum_value(getattr(item, "role", None)) or "user"
            blocks = cls._content_blocks(getattr(item, "content", None))
            if not blocks:
                continue
            messages.append(
                cls._msg_dump(
                    name=role,
                    role=role,
                    content=blocks,
                    backend=backend,
                ),
            )
        return messages

    @classmethod
    def _history_messages(
        cls,
        history: list[HarnessHistoryItem],
        backend: str,
    ) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        for item in history:
            role = "user" if item.kind == HarnessHistoryKind.USER else "assistant"
            if item.kind == HarnessHistoryKind.REASONING:
                block = {"type": "thinking", "thinking": item.text}
            elif item.kind == HarnessHistoryKind.TOOL_CALL:
                arguments = item.data.get("arguments") or {}
                block = {
                    "type": "tool_call",
                    "id": item.item_id,
                    "name": item.tool_name or "tool",
                    "input": json.dumps(
                        arguments,
                        ensure_ascii=False,
                        default=str,
                    ),
                }
            elif item.kind == HarnessHistoryKind.TOOL_OUTPUT:
                role = "assistant"
                block = {
                    "type": "tool_result",
                    "id": item.item_id,
                    "name": item.tool_name or "tool",
                    "output": item.text,
                }
            else:
                block = {"type": "text", "text": item.text}
            messages.append(
                cls._msg_dump(
                    name=role,
                    role=role,
                    content=[block],
                    backend=backend,
                    extra={"provider_item_id": item.item_id},
                ),
            )
        return messages

    @classmethod
    def _event_messages(
        cls,
        events: list[HarnessEvent],
        backend: str,
    ) -> list[dict[str, Any]]:
        history: list[HarnessHistoryItem] = []
        content_kind: HarnessHistoryKind | None = None
        content_text = ""
        tool_output: dict[str, str] = {}

        def flush_content() -> None:
            nonlocal content_kind, content_text
            if content_kind is not None and content_text:
                history.append(
                    HarnessHistoryItem(
                        kind=content_kind,
                        text=content_text,
                    ),
                )
            content_kind = None
            content_text = ""

        for event in events:
            if event.kind in {
                HarnessEventKind.TEXT_DELTA,
                HarnessEventKind.REASONING_DELTA,
            }:
                next_kind = (
                    HarnessHistoryKind.MESSAGE
                    if event.kind is HarnessEventKind.TEXT_DELTA
                    else HarnessHistoryKind.REASONING
                )
                if content_kind is not next_kind:
                    flush_content()
                    content_kind = next_kind
                content_text += event.text
            elif event.kind is HarnessEventKind.TOOL_STARTED:
                flush_content()
                history.append(
                    HarnessHistoryItem(
                        kind=HarnessHistoryKind.TOOL_CALL,
                        item_id=event.item_id,
                        tool_name=event.tool_name,
                        data=event.data,
                    ),
                )
                tool_output[event.item_id] = ""
            elif event.kind is HarnessEventKind.TOOL_PROGRESS:
                tool_output[event.item_id] = (
                    tool_output.get(event.item_id, "") + event.text
                )
            elif event.kind is HarnessEventKind.TOOL_COMPLETED:
                history.append(
                    HarnessHistoryItem(
                        kind=HarnessHistoryKind.TOOL_OUTPUT,
                        item_id=event.item_id,
                        tool_name=event.tool_name,
                        text=event.text or tool_output.get(event.item_id, ""),
                        data=event.data,
                    ),
                )
                tool_output.pop(event.item_id, None)
        flush_content()
        return cls._history_messages(history, backend)

    @staticmethod
    def _content_blocks(content: Any) -> list[dict[str, Any]]:
        if isinstance(content, str):
            return [{"type": "text", "text": content}]
        blocks: list[dict[str, Any]] = []
        for item in content or []:
            text = getattr(item, "text", None)
            if text:
                blocks.append({"type": "text", "text": str(text)})
                continue
            content_type = HarnessSessionBridge._enum_value(
                getattr(item, "type", None),
            )
            field_by_type = {
                "image": "image_url",
                "audio": "data",
                "video": "video_url",
                "file": "file_url",
            }
            field = field_by_type.get(content_type)
            source = getattr(item, field, None) if field else None
            if not source:
                continue
            source_text = str(source)
            if "://" not in source_text and not source_text.startswith(
                "data:",
            ):
                source_text = Path(source_text).expanduser().absolute().as_uri()
            default_media_types = {
                "image": "image/png",
                "audio": "audio/mpeg",
                "video": "video/mp4",
                "file": "application/octet-stream",
            }
            media_type = (
                mimetypes.guess_type(str(source))[0]
                or default_media_types[content_type]
            )
            block: dict[str, Any] = {
                "type": "data",
                "source": {
                    "type": "url",
                    "url": source_text,
                    "media_type": media_type,
                },
            }
            if content_type == "file":
                block["name"] = getattr(item, "filename", None)
            blocks.append(block)
        return blocks

    @staticmethod
    def _msg_dump(
        *,
        name: str,
        role: str,
        content: list[dict[str, Any]],
        backend: str,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        metadata = {"third_party_backend": backend}
        metadata.update(extra or {})
        message = Msg(
            name=name,
            role=role,
            content=content,
            metadata=metadata,
        )
        return message.model_dump(mode="json")

    @staticmethod
    def _enum_value(value: Any) -> str:
        return str(getattr(value, "value", value) or "")


__all__ = ["HarnessSessionBridge"]
