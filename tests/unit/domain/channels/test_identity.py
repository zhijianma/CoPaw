# -*- coding: utf-8 -*-
"""Tests for stable Channel instance identities."""

from pathlib import Path

from qwenpaw.domain.channels.identity import ChannelIdentity


def test_primary_identity_preserves_legacy_paths_and_sessions() -> None:
    identity = ChannelIdentity("feishu", "feishu")

    assert identity.is_primary is True
    assert identity.runtime_session_id("conversation") == "conversation"
    assert identity.platform_session_id("conversation") == "conversation"
    assert identity.state_dir(Path("workspace")) == Path("workspace")


def test_secondary_identity_isolates_sessions_and_state() -> None:
    identity = ChannelIdentity("feishu-a81c3f", "feishu")
    runtime_session = identity.runtime_session_id("conversation")

    assert identity.is_primary is False
    assert runtime_session == "feishu-a81c3f:conversation"
    assert identity.runtime_session_id(runtime_session) == runtime_session
    assert identity.platform_session_id(runtime_session) == "conversation"
    assert identity.state_dir(Path("workspace")).parent == (
        Path("workspace") / ".channel_instances"
    )
