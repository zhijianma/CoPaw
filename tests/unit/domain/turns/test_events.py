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


def test_agent_event_preserves_native_payload_without_ui_schema() -> None:
    payload = object()

    event = RuntimeEvent.agent_event(payload, turn_id="turn-1")

    assert event.type is RuntimeEventType.AGENT_EVENT
    assert event.turn_id == "turn-1"
    assert event.payload is payload
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
