# -*- coding: utf-8 -*-
"""Project canonical runtime facts into Channel presentation events."""

from __future__ import annotations

import uuid
from typing import Any, Iterator

from ...domain.channels.models import ReplyTarget
from ...domain.channels.ports import ReplyEvent, ReplyEventType
from ...domain.turns.events import RuntimeEvent, RuntimeEventType
from ...schemas import (
    ContentType,
    DataContent,
    Message,
    MessageType,
    Role,
    RunStatus,
    TextContent,
)


class ChannelEventProjector:
    """Stateful Channel presenter independent from the Console protocol."""

    def __init__(self, target: ReplyTarget) -> None:
        self._target = target
        self._text: dict[str, dict[str, Any]] = {}
        self._reasoning: dict[str, dict[str, Any]] = {}
        self._message = self._new_message(MessageType.MESSAGE)

    @staticmethod
    def _new_message(message_type: MessageType) -> Message:
        message = Message(
            id="message_" + uuid.uuid4().hex,
            type=message_type,
            role=Role.ASSISTANT,
            content=[],
            status=RunStatus.InProgress,
        )
        message.object = "message"
        message.name = "assistant"
        return message

    def _reply(
        self,
        event: RuntimeEvent,
        reply_type: ReplyEventType,
        payload: Any = None,
    ) -> ReplyEvent:
        return ReplyEvent(
            turn_id=event.turn_id,
            type=reply_type,
            target=self._target,
            payload=payload,
            metadata=event.metadata,
        )

    def _finalize_text(self, event: RuntimeEvent) -> Iterator[ReplyEvent]:
        if not self._message.content:
            return
        self._message.status = RunStatus.Completed
        yield self._reply(event, ReplyEventType.MESSAGE, self._message)
        self._message = self._new_message(MessageType.MESSAGE)
        self._text.clear()

    def project(  # pylint: disable=too-many-return-statements
        self,
        event: RuntimeEvent,
    ) -> Iterator[ReplyEvent]:
        """Yield zero or more Channel reply events for one runtime fact."""
        event_type = event.type
        data = dict(event.data)
        kind = str(data.get("content_kind") or "")

        if event_type is RuntimeEventType.TURN_STARTED:
            yield self._reply(event, ReplyEventType.STARTED)
            return
        if event_type is RuntimeEventType.HEARTBEAT:
            yield self._reply(event, ReplyEventType.HEARTBEAT)
            return
        if event_type is RuntimeEventType.MESSAGE:
            if isinstance(event.payload, Message):
                yield self._reply(
                    event,
                    ReplyEventType.MESSAGE,
                    event.payload,
                )
                return
            text = (
                getattr(event.payload, "get_text_content", lambda: "")() or ""
            )
            message = self._new_message(MessageType.MESSAGE)
            message.content.append(TextContent(text=text, index=0))
            message.status = RunStatus.Completed
            yield self._reply(event, ReplyEventType.MESSAGE, message)
            return
        if event_type is RuntimeEventType.TURN_FAILED:
            yield from self._finalize_text(event)
            yield self._reply(event, ReplyEventType.FAILED, event.payload)
            return
        if event_type is RuntimeEventType.TURN_CANCELLED:
            yield from self._finalize_text(event)
            yield self._reply(event, ReplyEventType.CANCELLED)
            return
        if event_type is RuntimeEventType.TURN_COMPLETED:
            yield from self._finalize_text(event)
            yield self._reply(event, ReplyEventType.COMPLETED)
            return

        if (
            event_type is RuntimeEventType.CUSTOM
            and event.metadata.get("reply_event_type") == "content"
        ):
            yield self._reply(event, ReplyEventType.CONTENT, event.payload)
            return

        if kind in {"text", "reasoning"}:
            yield from self._project_text(event, data, kind)
            return

        if event_type in {
            RuntimeEventType.TOOL_CALL_STARTED,
            RuntimeEventType.TOOL_RESULT_STARTED,
        }:
            yield from self._finalize_text(event)

        if event_type in {
            RuntimeEventType.TOOL_CALL_DELTA,
            RuntimeEventType.TOOL_RESULT_DELTA,
            RuntimeEventType.TOOL_RESULT_COMPLETED,
        }:
            content = DataContent(
                type=ContentType.DATA,
                data=data,
                status=RunStatus.InProgress,
            )
            yield self._reply(event, ReplyEventType.CONTENT, content)

    def _project_text(
        self,
        event: RuntimeEvent,
        data: dict[str, Any],
        kind: str,
    ) -> Iterator[ReplyEvent]:
        block_id = str(data.get("block_id") or kind)
        states = self._text if kind == "text" else self._reasoning
        state = states.get(block_id)
        if state is None:
            if kind == "reasoning":
                yield from self._finalize_text(event)
            message = (
                self._message
                if kind == "text"
                else self._new_message(MessageType.REASONING)
            )
            state = {
                "message": message,
                "text": "",
                "index": len(states),
            }
            states[block_id] = state
            yield self._reply(event, ReplyEventType.MESSAGE, message)

        if event.type is RuntimeEventType.CONTENT_DELTA:
            delta = str(data.get("delta") or "")
            state["text"] += delta
            chunk = TextContent(
                text=delta,
                delta=True,
                index=state["index"],
                status=RunStatus.InProgress,
            )
            chunk.msg_id = state["message"].id
            yield self._reply(event, ReplyEventType.CONTENT, chunk)
            return

        if event.type is RuntimeEventType.CONTENT_COMPLETED:
            final = TextContent(
                text=state["text"],
                index=state["index"],
                status=RunStatus.Completed,
            )
            final.msg_id = state["message"].id
            state["message"].content.append(final)
            yield self._reply(event, ReplyEventType.CONTENT, final)
            if kind == "reasoning":
                state["message"].status = RunStatus.Completed
                yield self._reply(
                    event,
                    ReplyEventType.MESSAGE,
                    state["message"],
                )


__all__ = ["ChannelEventProjector"]
