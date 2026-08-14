# -*- coding: utf-8 -*-
"""Present transport-neutral runtime events as Console response objects."""

from __future__ import annotations

from typing import Any, AsyncGenerator

from ...domain.turns.events import RuntimeEvent, RuntimeEventType


class ConsoleEventPresenter:
    """Compatibility presenter for the existing Console stream protocol."""

    def __init__(
        self,
        *,
        session_id: str = "",
        envelope: Any | None = None,
    ) -> None:
        if envelope is None:
            # Import lazily while Envelope remains in the legacy runtime
            # package. This avoids a package initialization cycle until the
            # implementation is physically moved into this transport.
            from ...runtime.envelope import Envelope

            envelope = Envelope(session_id=session_id)
        self.envelope = envelope

    async def present(
        self,
        event: RuntimeEvent,
    ) -> AsyncGenerator[Any, None]:
        """Map one runtime event to zero or more Console response objects."""
        if event.type is RuntimeEventType.TURN_STARTED:
            stream = self.envelope.emit_response_created()
        elif event.type is RuntimeEventType.AGENT_EVENT:
            stream = self.envelope.translate_event(event.payload)
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
            raise ValueError(f"Unsupported runtime event: {event.type}")

        async for item in stream:
            yield item


__all__ = ["ConsoleEventPresenter"]
