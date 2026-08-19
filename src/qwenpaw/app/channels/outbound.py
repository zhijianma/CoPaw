# -*- coding: utf-8 -*-
"""Project canonical events for proactive Channel delivery."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from ...domain.channels.models import ReplyTarget
from ...domain.channels.ports import ReplyEvent
from ...domain.turns.events import RuntimeEvent
from .event_projector import ChannelEventProjector


class ChannelOutboundPresenter:
    """Present one runtime stream as platform-neutral Channel payloads."""

    def __init__(
        self,
        *,
        channel_type: str,
        conversation_id: str,
        recipient_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._projector = ChannelEventProjector(
            ReplyTarget(
                channel_type=channel_type,
                conversation_id=conversation_id,
                recipient_id=recipient_id or None,
                metadata=metadata or {},
            ),
        )

    def present(self, event: RuntimeEvent) -> Iterator[ReplyEvent]:
        """Project one runtime fact without discarding its delivery target."""
        yield from self._projector.project(event)


__all__ = ["ChannelOutboundPresenter"]
