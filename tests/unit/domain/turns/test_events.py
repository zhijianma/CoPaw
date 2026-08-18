# -*- coding: utf-8 -*-
"""Contracts for transport-neutral runtime events."""

from __future__ import annotations

from datetime import timezone

import pytest

from qwenpaw.domain.turns.events import (
    EventRecord,
    RuntimeEvent,
    RuntimeEventType,
)


def test_canonical_event_copies_normalized_data() -> None:
    data = {"content_kind": "text", "delta": "hello"}

    event = RuntimeEvent.canonical(
        RuntimeEventType.CONTENT_DELTA,
        turn_id="turn-1",
        data=data,
    )
    data["delta"] = "changed"

    assert event.type is RuntimeEventType.CONTENT_DELTA
    assert event.turn_id == "turn-1"
    assert event.data["delta"] == "hello"
    assert event.occurred_at.tzinfo is timezone.utc


def test_heartbeat_has_no_transport_payload() -> None:
    event = RuntimeEvent.heartbeat(turn_id="turn-1")

    assert event.type is RuntimeEventType.HEARTBEAT
    assert event.payload is None


def test_event_record_rejects_negative_cursor() -> None:
    with pytest.raises(ValueError, match="cursor"):
        EventRecord(
            cursor=-1,
            event=RuntimeEvent.heartbeat(),
        )
