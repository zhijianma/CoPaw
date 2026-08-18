# -*- coding: utf-8 -*-
"""Select the reply protocol at the Channel application boundary."""

from __future__ import annotations

from typing import Any, AsyncIterable, AsyncIterator

from ...domain.channels.models import ReplyTarget
from ...domain.channels.ports import ReplyEvent
from ...domain.turns.events import RuntimeEvent
from ...protocols.builtins import create_default_presenter
from ...runtime.legacy_reply_adapter import LegacyReplyAdapter


class ReplyPresentationAdapter:
    """Present canonical events before legacy Channel delivery hooks."""

    def __init__(
        self,
        *,
        turn_id: str,
        target: ReplyTarget,
        conversation_id: str,
    ) -> None:
        self._legacy = LegacyReplyAdapter(turn_id, target)
        self._presenter, self._context = create_default_presenter(
            conversation_id=conversation_id,
            turn_id=turn_id,
        )

    async def project(
        self,
        event: Any,
    ) -> AsyncIterator[tuple[Any, ReplyEvent]]:
        """Yield protocol output together with its delivery classification."""
        if isinstance(event, RuntimeEvent):
            async for output in self._presenter.present(event, self._context):
                yield output, self._legacy.project(output)
            return
        yield event, self._legacy.project(event)


async def present_reply_stream(
    stream: AsyncIterable[Any],
    *,
    request: Any,
    channel_type: str,
    conversation_id: str,
) -> AsyncIterator[Any]:
    """Present a possibly canonical stream for direct Channel consumers."""
    target = getattr(request, "reply_target", None)
    if not isinstance(target, ReplyTarget):
        target = ReplyTarget(
            channel_type=channel_type,
            conversation_id=conversation_id,
        )
    turn_id = str(
        getattr(request, "turn_id", "")
        or getattr(request, "id", "")
        or conversation_id,
    )
    adapter = ReplyPresentationAdapter(
        turn_id=turn_id,
        target=target,
        conversation_id=conversation_id,
    )
    async for raw_event in stream:
        async for event, _ in adapter.project(raw_event):
            yield event


__all__ = ["ReplyPresentationAdapter", "present_reply_stream"]
