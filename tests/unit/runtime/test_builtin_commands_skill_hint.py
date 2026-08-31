# -*- coding: utf-8 -*-
"""Tests for slash-skill HintBlock migration."""

from types import SimpleNamespace

import pytest
from agentscope.message import HintBlock, Msg, TextBlock

from qwenpaw.agents.memory.hint_projection import (
    project_messages_for_memory,
)
from qwenpaw.runtime.builtin_commands import (
    _build_skill_injection,
    _skill_fallback_handler,
)


@pytest.mark.asyncio
async def test_skill_keeps_typed_text_and_projects_legacy_memory(
    monkeypatch,
    tmp_path,
) -> None:
    skill_dir = tmp_path / "demo"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: Demo\ndescription: Test skill\n---\nFollow this skill.",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "qwenpaw.agents.skill_system.registry.resolve_effective_skills",
        lambda *_args: ["demo"],
    )
    monkeypatch.setattr(
        "qwenpaw.agents.skill_system.registry.get_workspace_skills_dir",
        lambda *_args: tmp_path,
    )
    typed = "/demo do work"
    user = Msg(
        name="user",
        role="user",
        content=[TextBlock(text=typed)],
    )
    ctx = SimpleNamespace(
        workspace=SimpleNamespace(workspace_dir=tmp_path),
        request=SimpleNamespace(channel="console"),
        input_msgs=[user],
    )

    result = await _skill_fallback_handler(typed, ctx)

    assert result is None
    assert user.get_text_content() == typed
    assert isinstance(ctx.input_msgs[1].content[0], HintBlock)
    projected = project_messages_for_memory(ctx.input_msgs)
    assert projected[0].get_text_content() == _build_skill_injection(
        typed,
        "Demo",
        "Test skill",
        skill_dir,
        "Follow this skill.",
    )
