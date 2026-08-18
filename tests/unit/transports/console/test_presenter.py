# -*- coding: utf-8 -*-
"""Console presenter contracts for RuntimeEvent compatibility."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import pytest

from qwenpaw.domain.turns.events import RuntimeEvent, RuntimeEventType
from qwenpaw.protocols.console.presenter import ConsoleEventPresenter


class _Envelope:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    async def emit_response_created(self) -> AsyncGenerator[str, None]:
        self.calls.append(("started", None))
        yield "started"

    async def translate_event(
        self,
        payload: Any,
    ) -> AsyncGenerator[str, None]:
        self.calls.append(("agent", payload))
        yield "agent"

    async def heartbeat(self) -> AsyncGenerator[str, None]:
        self.calls.append(("heartbeat", None))
        yield "heartbeat"

    async def from_msg(self, payload: Any) -> AsyncGenerator[str, None]:
        self.calls.append(("message", payload))
        yield "message"

    async def finalize(self) -> AsyncGenerator[str, None]:
        self.calls.append(("completed", None))
        yield "completed"

    async def error_envelope(
        self,
        error_text: str,
        error_code: str,
    ) -> AsyncGenerator[str, None]:
        self.calls.append(("failed", (error_text, error_code)))
        yield "failed"

    async def cancel_envelope(self) -> AsyncGenerator[str, None]:
        self.calls.append(("cancelled", None))
        yield "cancelled"


async def _present(
    presenter: ConsoleEventPresenter,
    event: RuntimeEvent,
) -> list[Any]:
    return [item async for item in presenter.present(event)]


@pytest.mark.asyncio
async def test_presenter_maps_every_runtime_event() -> None:
    envelope = _Envelope()
    presenter = ConsoleEventPresenter(envelope=envelope)
    content = RuntimeEvent.canonical(
        RuntimeEventType.CONTENT_DELTA,
        data={
            "reply_id": "reply-1",
            "block_id": "block-1",
            "content_kind": "text",
            "delta": "hello",
        },
    )
    message = object()

    outputs = []
    for event in (
        RuntimeEvent.turn_started(),
        content,
        RuntimeEvent.heartbeat(),
        RuntimeEvent.message(message),
        RuntimeEvent.turn_completed(),
        RuntimeEvent.turn_failed("broken", "test_error"),
        RuntimeEvent.turn_cancelled(),
    ):
        outputs.extend(await _present(presenter, event))

    assert outputs == [
        "started",
        "agent",
        "heartbeat",
        "message",
        "completed",
        "failed",
        "cancelled",
    ]
    assert envelope.calls[:1] == [("started", None)]
    native_view = envelope.calls[1][1]
    assert native_view.type == RuntimeEventType.CONTENT_DELTA.value
    assert native_view.delta == "hello"
    assert envelope.calls[2:] == [
        ("heartbeat", None),
        ("message", message),
        ("completed", None),
        ("failed", ("broken", "test_error")),
        ("cancelled", None),
    ]


@pytest.mark.asyncio
async def test_presenter_rejects_unknown_event_type() -> None:
    presenter = ConsoleEventPresenter(envelope=_Envelope())
    event = RuntimeEvent(type="unknown")  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="Unsupported runtime event"):
        await _present(presenter, event)
