# -*- coding: utf-8 -*-
"""Present canonical runtime events as existing Console response objects."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, AsyncGenerator

from ...domain.turns.events import RuntimeEvent, RuntimeEventType
from ..ports import PresentationContext


def _protocol_event_view(event: RuntimeEvent) -> SimpleNamespace:
    """Expose canonical fields to the Console protocol state machine."""
    data = dict(event.data)
    return SimpleNamespace(
        type=event.type.value,
        metadata=dict(event.metadata),
        **data,
    )


class ConsoleEventPresenter:
    """Compatibility presenter for the existing Console stream protocol."""

    def __init__(
        self,
        *,
        session_id: str = "",
        envelope: Any | None = None,
    ) -> None:
        if envelope is None:
            from .envelope import Envelope

            envelope = Envelope(session_id=session_id)
        self.envelope = envelope

    async def present(
        self,
        event: RuntimeEvent,
        context: PresentationContext | None = None,
    ) -> AsyncGenerator[Any, None]:
        """Map one canonical runtime event to Console response objects."""
        del context
        if not isinstance(event.type, RuntimeEventType):
            raise ValueError(f"Unsupported runtime event: {event.type}")
        if event.type is RuntimeEventType.TURN_STARTED:
            stream = self.envelope.emit_response_created()
        elif event.type is RuntimeEventType.HEARTBEAT:
            stream = self.envelope.heartbeat()
        elif event.type is RuntimeEventType.MESSAGE:
            stream = self.envelope.from_msg(event.payload)
        elif event.type is RuntimeEventType.TURN_COMPLETED:
            stream = self.envelope.finalize()
        elif event.type is RuntimeEventType.TURN_FAILED:
            failure = event.payload
            stream = self.envelope.error_envelope(
                failure.error_text,
                failure.error_code,
            )
        elif event.type is RuntimeEventType.TURN_CANCELLED:
            stream = self.envelope.cancel_envelope()
        else:
            stream = self.envelope.translate_event(_protocol_event_view(event))

        async for item in stream:
            yield item


__all__ = ["ConsoleEventPresenter"]
