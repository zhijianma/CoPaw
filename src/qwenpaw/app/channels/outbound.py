# -*- coding: utf-8 -*-
"""Project canonical events for proactive Channel delivery."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from ...domain.channels.models import ReplyTarget
from ...domain.channels.ports import ReplyEventType
from ...domain.turns.events import RuntimeEvent, RuntimeFailure
from ...schemas import Message, MessageType, Role, RunStatus, TextContent
from .event_projector import ChannelEventProjector


class ChannelOutboundPresenter:
    """Present one runtime stream as platform-neutral Channel payloads."""

    def __init__(
        self,
        *,
        channel_type: str,
        conversation_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._projector = ChannelEventProjector(
            ReplyTarget(
                channel_type=channel_type,
                conversation_id=conversation_id,
                metadata=metadata or {},
            ),
        )

    def present(self, event: RuntimeEvent) -> Iterator[Any]:
        """Yield only payloads understood by Channel send hooks."""
        for reply in self._projector.project(event):
            if reply.type in {
                ReplyEventType.CONTENT,
                ReplyEventType.MESSAGE,
            } and reply.payload is not None:
                yield reply.payload
            elif reply.type is ReplyEventType.FAILED and isinstance(
                reply.payload,
                RuntimeFailure,
            ):
                message = Message(
                    type=MessageType.MESSAGE,
                    role=Role.ASSISTANT,
                    status=RunStatus.Completed,
                    content=[TextContent(text=reply.payload.error_text)],
                )
                message.object = "message"
                yield message


__all__ = ["ChannelOutboundPresenter"]
