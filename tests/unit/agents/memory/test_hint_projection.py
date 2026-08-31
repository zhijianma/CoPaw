# -*- coding: utf-8 -*-
"""Tests for the HintBlock compatibility view used by memory backends."""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agentscope.message import (
    DataBlock,
    HintBlock,
    Msg,
    TextBlock,
    URLSource,
)
from hypothesis import given, strategies as st
from pydantic import ValidationError
from reme.steps.evolve._evolve import format_history

from qwenpaw.agents.hints import (
    HINT_POSITION_AFTER_BLOCK_ID,
    HINT_POSITION_APPEND_TEXT,
    HINT_POSITION_BEFORE_FIRST_TEXT,
    HINT_PROJECTION_METADATA_KEY,
    HINT_PROJECTION_SCHEMA_VERSION,
    HINT_SOURCE_BACKGROUND_TOOL,
    HINT_SOURCE_BOOTSTRAP,
    HINT_SOURCE_CONTEXT,
    HINT_SOURCE_SKILL,
    HINT_SOURCE_UPLOADED_FILE,
    make_hint_carrier,
)
from qwenpaw.agents.memory.hint_projection import (
    project_messages_for_memory,
)
from qwenpaw.agents.memory.adbpg_memory_manager import ADBPGMemoryManager
from qwenpaw.agents.memory.reme_light_memory_manager import (
    ReMeLightMemoryManager,
)


def _user(*blocks, msg_id: str = "user-1") -> Msg:
    return Msg(
        id=msg_id,
        name="user",
        role="user",
        content=list(blocks),
    )


def _texts(msg: Msg) -> list[str]:
    return [
        block.text for block in msg.content if isinstance(block, TextBlock)
    ]


def test_hintblock_is_valid_only_in_assistant_message() -> None:
    block = HintBlock(hint="private", source="test")
    Msg(name="agent", role="assistant", content=[block])

    with pytest.raises(ValidationError):
        Msg(name="user", role="user", content=[block])
    with pytest.raises(ValidationError):
        Msg(name="system", role="system", content=[block])


def test_no_hint_fast_path_preserves_message_objects() -> None:
    original = _user(TextBlock(text="hello"))

    projected = project_messages_for_memory([original])

    assert projected == [original]
    assert projected[0] is original


def test_background_hint_expands_text_and_data_in_place() -> None:
    data = DataBlock(
        id="image-1",
        name="result.png",
        source=URLSource(
            url="https://example.invalid/result.png",
            media_type="image/png",
        ),
    )
    carrier = make_hint_carrier(
        hint=[
            TextBlock(text="<system-notification>done</system-notification>"),
            data,
        ],
        source=HINT_SOURCE_BACKGROUND_TOOL,
    )
    before = carrier.model_dump(mode="json")

    projected = project_messages_for_memory([carrier])

    assert [block.type for block in projected[0].content] == ["text", "data"]
    assert projected[0].content[1].id == "image-1"
    assert carrier.model_dump(mode="json") == before


def test_reme_history_is_exactly_equal_before_and_after_migration() -> None:
    text = "<system-reminder>remember this forever</system-reminder>"
    legacy = Msg(
        id="legacy-message",
        name="system",
        role="assistant",
        created_at="2026-08-31T10:00:00",
        content=[
            TextBlock(
                id="legacy-block",
                created_at="2026-08-31T10:00:00",
                text=text,
            ),
        ],
    )
    migrated = Msg(
        id="legacy-message",
        name="system",
        role="assistant",
        created_at="2026-08-31T10:00:00",
        content=[
            HintBlock(
                id="legacy-block",
                created_at="2026-08-31T10:00:00",
                hint=text,
                source=HINT_SOURCE_BACKGROUND_TOOL,
            ),
        ],
    )

    projected = project_messages_for_memory([migrated])

    assert format_history(projected) == format_history([legacy])
    assert format_history([migrated]) == "(empty)"


@pytest.mark.asyncio
async def test_reme_direct_summarize_projects_hint_before_job() -> None:
    manager = ReMeLightMemoryManager.__new__(ReMeLightMemoryManager)
    manager.agent_id = "agent-1"
    manager._run_reme_job = AsyncMock(
        return_value=SimpleNamespace(answer="stored"),
    )
    carrier = make_hint_carrier(
        hint="<system-reminder>remember this</system-reminder>",
        source=HINT_SOURCE_BACKGROUND_TOOL,
    )

    result = await manager.summarize(
        [carrier],
        session_id="session-1",
    )

    assert result == "stored"
    payload = manager._run_reme_job.await_args.kwargs["messages"]
    assert payload[0]["content"][0]["type"] == "text"
    assert payload[0]["content"][0]["text"] == (
        "<system-reminder>remember this</system-reminder>"
    )


@pytest.mark.parametrize(
    ("source", "position", "expected"),
    [
        (
            HINT_SOURCE_BOOTSTRAP,
            HINT_POSITION_BEFORE_FIRST_TEXT,
            ["guidancetyped"],
        ),
        (HINT_SOURCE_SKILL, HINT_POSITION_APPEND_TEXT, ["typedskill body"]),
    ],
)
def test_merge_hint_restores_legacy_user_text(
    source: str,
    position: str,
    expected: list[str],
) -> None:
    user = _user(TextBlock(text="typed"))
    hint_text = "guidance" if source == HINT_SOURCE_BOOTSTRAP else "skill body"
    carrier = make_hint_carrier(
        hint=hint_text,
        source=source,
        target_msg_id=user.id,
        position=position,
    )

    projected = project_messages_for_memory([user, carrier])

    assert len(projected) == 1
    assert _texts(projected[0]) == expected
    assert _texts(user) == ["typed"]


def test_adbpg_user_payload_is_equal_after_skill_projection() -> None:
    legacy = _user(TextBlock(text="typed\n\n<skill>body</skill>"))
    migrated_user = _user(TextBlock(text="typed"))
    carrier = make_hint_carrier(
        hint="\n\n<skill>body</skill>",
        source=HINT_SOURCE_SKILL,
        target_msg_id=migrated_user.id,
        position=HINT_POSITION_APPEND_TEXT,
    )

    projected = project_messages_for_memory([migrated_user, carrier])

    assert ADBPGMemoryManager._filter_user_messages(projected) == (
        ADBPGMemoryManager._filter_user_messages([legacy])
    )


def test_uploaded_file_hint_merges_after_anchored_data() -> None:
    data = DataBlock(
        id="file-1",
        name="notes.txt",
        source=URLSource(
            url="file:///workspace/notes.txt",
            media_type="text/plain",
        ),
    )
    user = _user(data, TextBlock(text="summarize it"))
    carrier = make_hint_carrier(
        hint="downloaded to /workspace/notes.txt",
        source=HINT_SOURCE_UPLOADED_FILE,
        target_msg_id=user.id,
        position=HINT_POSITION_AFTER_BLOCK_ID,
        anchor_block_id=data.id,
    )

    projected = project_messages_for_memory([user, carrier])

    assert [block.type for block in projected[0].content] == [
        "data",
        "text",
        "text",
    ]
    assert _texts(projected[0]) == [
        "downloaded to /workspace/notes.txt",
        "summarize it",
    ]


def test_excluded_hint_does_not_remove_assistant_text() -> None:
    carrier = Msg(
        name="agent",
        role="assistant",
        content=[
            TextBlock(text="visible answer"),
            HintBlock(hint="runtime only", source=HINT_SOURCE_CONTEXT),
        ],
    )

    projected = project_messages_for_memory([carrier])

    assert _texts(projected[0]) == ["visible answer"]


def test_unknown_source_expands_instead_of_losing_memory(
    caplog: pytest.LogCaptureFixture,
) -> None:
    carrier = Msg(
        name="agent",
        role="assistant",
        content=[HintBlock(hint="keep forever", source="third-party")],
    )

    projected = project_messages_for_memory([carrier])

    assert _texts(projected[0]) == ["keep forever"]
    assert "source is unknown" in caplog.text


def test_missing_merge_metadata_falls_back_to_same_message(
    caplog: pytest.LogCaptureFixture,
) -> None:
    carrier = Msg(
        name="agent",
        role="assistant",
        content=[HintBlock(hint="do not lose", source=HINT_SOURCE_SKILL)],
    )

    projected = project_messages_for_memory([carrier])

    assert _texts(projected[0]) == ["do not lose"]
    assert "target user metadata is missing" in caplog.text


def test_unknown_schema_version_falls_back_without_loss() -> None:
    user = _user(TextBlock(text="typed"))
    carrier = make_hint_carrier(
        hint="skill body",
        source=HINT_SOURCE_SKILL,
        target_msg_id=user.id,
        position=HINT_POSITION_APPEND_TEXT,
    )
    carrier.metadata[HINT_PROJECTION_METADATA_KEY]["version"] = (
        HINT_PROJECTION_SCHEMA_VERSION + 1
    )

    projected = project_messages_for_memory([user, carrier])

    assert _texts(projected[0]) == ["typed"]
    assert _texts(projected[1]) == ["skill body"]


@given(st.lists(st.text(max_size=80), min_size=1, max_size=12))
def test_projection_is_pure_idempotent_and_ordered(texts: list[str]) -> None:
    messages = [
        Msg(
            id=f"msg-{idx}",
            name="agent",
            role="assistant",
            content=[
                HintBlock(
                    id=f"hint-{idx}",
                    hint=text,
                    source=HINT_SOURCE_BACKGROUND_TOOL,
                ),
            ],
        )
        for idx, text in enumerate(texts)
    ]
    before = deepcopy(messages)

    projected = project_messages_for_memory(messages)
    projected_twice = project_messages_for_memory(projected)

    assert messages == before
    assert projected_twice == projected
    assert [_texts(msg)[0] for msg in projected] == texts


def test_projection_survives_message_json_round_trip() -> None:
    user = _user(TextBlock(text="typed"))
    carrier = make_hint_carrier(
        hint="skill body",
        source=HINT_SOURCE_SKILL,
        target_msg_id=user.id,
        position=HINT_POSITION_APPEND_TEXT,
    )
    restored = [
        Msg.model_validate(msg.model_dump(mode="json"))
        for msg in (user, carrier)
    ]

    projected = project_messages_for_memory(restored)

    assert _texts(projected[0]) == ["typedskill body"]
