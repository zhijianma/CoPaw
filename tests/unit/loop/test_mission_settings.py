# -*- coding: utf-8 -*-
"""Tests for user-editable Mission defaults."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from agentscope.message import HintBlock, Msg, TextBlock
from pydantic import ValidationError

from qwenpaw.agents.hints import (
    HINT_POSITION_REPLACE_CONTENT,
    HINT_SOURCE_MISSION,
    make_hint_carrier,
)
from qwenpaw.agents.memory.hint_projection import (
    project_messages_for_memory,
)
from qwenpaw.config.config import MissionLoopModeConfig
from qwenpaw.modes.mission.handler import (
    build_mission_hint_parts,
    parse_mission_args,
    start_mission,
)
from qwenpaw.modes.mission.prompts import build_master_prompt
from qwenpaw.modes.mission.state import read_loop_config


def test_mission_config_defaults_and_bounds() -> None:
    """Mission settings expose conservative defaults with validation."""
    config = MissionLoopModeConfig()

    assert config.max_iterations == 20
    assert config.max_retries_per_story == 3
    assert config.default_verification_instructions == ""
    assert config.default_verify_command == ""

    with pytest.raises(ValidationError):
        MissionLoopModeConfig(max_retries_per_story=11)


def test_mission_hint_projects_exact_legacy_prompt_without_duplication() -> (
    None
):
    task = "Implement the approved feature"
    legacy = (
        "Starting Mission Mode: `mission-1`.\n\n"
        "Task (saved in `/tmp/mission-1/task.md`):\n"
        f"> {task}\n\n"
        "Master instructions\n\nPhase 1"
    )
    user = Msg(
        name="user",
        role="user",
        content=[TextBlock(text=task)],
    )
    carrier = make_hint_carrier(
        hint=build_mission_hint_parts(legacy, task),
        source=HINT_SOURCE_MISSION,
        target_msg_id=user.id,
        position=HINT_POSITION_REPLACE_CONTENT,
        renderer_version=1,
        renderer_context={
            "mission_name": "mission-1",
            "loop_dir": "/tmp/mission-1",
        },
    )

    assert isinstance(carrier.content[0], HintBlock)
    assert task not in str(carrier.metadata)
    assert (
        sum(
            part.text.count(task)
            for part in carrier.content[0].hint
            if isinstance(part, TextBlock)
        )
        == 0
    )
    projected = project_messages_for_memory([user, carrier])
    assert projected[0].get_text_content() == legacy
    assert user.get_text_content() == task


def test_mission_args_use_defaults_and_allow_command_override() -> None:
    """Per-mission arguments override only values explicitly provided."""
    defaults = parse_mission_args(
        "implement the feature",
        default_max_iterations=12,
        default_verify_command="npm test",
    )
    override = parse_mission_args(
        "implement the feature --max-iterations 7 --verify pytest",
        default_max_iterations=12,
        default_verify_command="npm test",
    )

    assert defaults["max_iterations"] == 12
    assert defaults["verify_commands"] == "npm test"
    assert override["max_iterations"] == 7
    assert override["verify_commands"] == "pytest"


def test_master_prompt_uses_configured_story_retry_limit() -> None:
    """Retry configuration replaces the previous hard-coded prompt value."""
    prompt = build_master_prompt(
        loop_dir="/tmp/mission",
        agent_id="agent",
        max_retries_per_story=6,
    )

    assert "Max 6 retries per story" in prompt
    assert "Max 3 retries per story" not in prompt


def test_master_prompt_includes_verification_instructions() -> None:
    """Verifier receives natural-language guidance separately from commands."""
    prompt = build_master_prompt(
        loop_dir="/tmp/mission",
        agent_id="agent",
        verification_instructions=(
            "Check Windows path handling and inspect the rendered UI."
        ),
        verify_commands="pytest -q",
    )

    assert "Check Windows path handling" in prompt
    assert "**Verify command**: pytest -q" in prompt


@pytest.mark.asyncio
async def test_start_mission_persists_editable_defaults(tmp_path) -> None:
    """New missions persist settings used by the existing workflow."""
    git_context = {
        "git_installed": False,
        "is_git_repo": False,
        "default_branch": "",
        "repo_root": "",
    }
    with patch(
        "qwenpaw.modes.mission.handler.detect_git_context",
        new=AsyncMock(return_value=git_context),
    ):
        _, loop_dir = await start_mission(
            task_text="Implement the approved feature",
            project_dir=tmp_path,
            agent_workspace_dir=tmp_path / "agent-workspace",
            agent_id="agent",
            session_id="session",
            verify_commands="pytest -q",
            verification_instructions="Check accessibility manually.",
            max_iterations=14,
            max_retries_per_story=5,
        )

    config = read_loop_config(loop_dir)
    assert config["max_iterations"] == 14
    assert config["max_retries_per_story"] == 5
    assert config["verify_commands"] == "pytest -q"
    assert config["verification_instructions"] == (
        "Check accessibility manually."
    )
    assert loop_dir.parent == tmp_path / ".qwenpaw" / "missions"
    assert config["source_project_dir"] == str(tmp_path)
    assert config["workspace_dir"] == str(tmp_path / "agent-workspace")
    assert config["mission_run_dir"] == str(tmp_path)
