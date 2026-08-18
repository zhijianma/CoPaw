# -*- coding: utf-8 -*-
"""Platform-side delivery strategy for the compatibility event stream."""

from __future__ import annotations

from typing import Any

from ...domain.channels.ports import ReplyEvent, ReplyEventType
from ...domain.turns.events import RuntimeFailure
from ...schemas import RunStatus


class ChannelReplyDelivery:
    """Dispatch reply facts to Channel send hooks outside Runtime."""

    def __init__(
        self,
        *,
        channel: Any,
        request: Any,
        to_handle: str,
        send_meta: dict[str, Any],
    ) -> None:
        self._channel = channel
        self._request = request
        self._to_handle = to_handle
        self._send_meta = send_meta
        self.last_response: Any = None
        self.last_failure: RuntimeFailure | None = None

    async def deliver(self, event: ReplyEvent) -> None:
        """Deliver one reply event using only adapter-owned behavior."""
        payload = event.payload
        if event.type == ReplyEventType.CONTENT:
            await self._channel.on_event_content(
                self._request,
                self._to_handle,
                payload,
                self._send_meta,
            )
            return
        if event.type == ReplyEventType.MESSAGE:
            if getattr(payload, "status", None) == RunStatus.Completed:
                await self._channel.on_event_message_completed(
                    self._request,
                    self._to_handle,
                    payload,
                    self._send_meta,
                )
            return
        if event.type in {
            ReplyEventType.COMPLETED,
            ReplyEventType.FAILED,
        }:
            self.last_response = payload
            if isinstance(payload, RuntimeFailure):
                self.last_failure = payload
            await self._channel.on_event_response(
                self._request,
                payload,
            )


__all__ = ["ChannelReplyDelivery"]
