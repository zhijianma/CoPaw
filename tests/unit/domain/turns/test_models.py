# -*- coding: utf-8 -*-
"""Contracts for the transport-neutral turn domain."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from qwenpaw.domain.turns.models import RequestSource, TurnRequest


def test_turn_request_normalizes_mutable_inputs() -> None:
    messages = ["hello"]
    context = {"project_dir": "/tmp/project"}

    request = TurnRequest(
        turn_id="turn-1",
        agent_id="agent-1",
        session_id="session-1",
        user_id="user-1",
        messages=messages,
        source=RequestSource(kind="console"),
        context=context,
    )

    messages.append("late mutation")
    context["project_dir"] = "/tmp/changed"

    assert request.messages == ("hello",)
    assert request.context == {"project_dir": "/tmp/project"}
    with pytest.raises(TypeError):
        request.context["new"] = "value"  # type: ignore[index]


def test_turn_request_is_frozen() -> None:
    request = TurnRequest(
        turn_id="turn-1",
        agent_id="agent-1",
        session_id="session-1",
        user_id="user-1",
        messages=(),
        source=RequestSource(kind="system"),
    )

    with pytest.raises(FrozenInstanceError):
        request.agent_id = "other"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("turn_id", ""),
        ("agent_id", ""),
        ("session_id", ""),
    ),
)
def test_turn_request_rejects_missing_identity(
    field: str,
    value: str,
) -> None:
    values = {
        "turn_id": "turn-1",
        "agent_id": "agent-1",
        "session_id": "session-1",
        "user_id": "user-1",
        "messages": (),
        "source": RequestSource(kind="console"),
    }
    values[field] = value

    with pytest.raises(ValueError, match=field):
        TurnRequest(**values)


def test_request_source_rejects_unknown_kind() -> None:
    with pytest.raises(ValueError, match="kind"):
        RequestSource(kind="unknown")
