# -*- coding: utf-8 -*-
"""Dependency guards for Channel, Transport, and Protocol boundaries."""

from pathlib import Path

from qwenpaw.domain.turns.models import RequestSource


def _source(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_runtime_core_has_no_console_protocol_dependency() -> None:
    source = _source("src/qwenpaw/runtime/runtime.py")

    assert "ConsoleEventPresenter" not in source
    assert "transports.console" not in source
    assert "protocols.console" not in source
    assert "protocols.builtins" not in source
    assert "ReplyProjector" not in source
    assert "ReplyEvent" not in source


def test_workspace_is_a_protocol_neutral_execution_boundary() -> None:
    source = _source("src/qwenpaw/app/workspace/workspace.py")

    assert "ConsoleTurnIngress" not in source
    assert "create_default_presenter" not in source
    assert "protocols." not in source
    assert "def stream_query(" not in source
    assert "def stream_channel_events(" not in source
    assert "def stream_events(" in source


def test_internal_callers_do_not_masquerade_as_console_requests() -> None:
    sources = "\n".join(
        _source(path)
        for path in (
            "src/qwenpaw/app/crons/executor.py",
            "src/qwenpaw/app/crons/heartbeat.py",
            "src/qwenpaw/pawapp/context.py",
            "src/qwenpaw/agents/acp/server.py",
            "src/qwenpaw/cli/task_cmd.py",
        )
    )

    assert "AgentRequest" not in sources
    assert ".stream_query(" not in sources


def test_runtime_hooks_read_only_canonical_request_fields() -> None:
    sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in Path("src/qwenpaw/hooks").rglob("*.py")
    )

    assert 'getattr(request, "request_context"' not in sources
    assert 'getattr(ctx.request, "request_context"' not in sources
    assert 'getattr(request, "channel"' not in sources
    assert 'getattr(ctx.request, "channel"' not in sources


def test_turn_domain_has_no_agentscope_dependency() -> None:
    source = "\n".join(
        [
            _source("src/qwenpaw/domain/turns/events.py"),
            _source("src/qwenpaw/domain/turns/models.py"),
        ],
    )

    assert "agentscope" not in source.lower()


def test_protocol_ports_and_console_presenter_have_no_engine_dependency() -> (
    None
):
    source = "\n".join(
        [
            _source("src/qwenpaw/protocols/ports.py"),
            _source("src/qwenpaw/protocols/registry.py"),
            _source("src/qwenpaw/protocols/console/presenter.py"),
        ],
    )

    assert "agentscope" not in source.lower()


def test_console_protocol_state_machine_has_no_engine_dependency() -> None:
    source = _source("src/qwenpaw/protocols/console/envelope.py")

    assert "agentscope.event" not in source.lower()


def test_request_source_accepts_protocol_extensions() -> None:
    source = RequestSource(protocol="future-protocol", endpoint_id="edge-1")

    assert source.protocol == "future-protocol"
    assert source.endpoint_id == "edge-1"


def test_channel_layer_has_no_console_request_or_response_schema() -> None:
    channel_sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in Path("src/qwenpaw/app/channels").rglob("*.py")
    )

    assert "AgentRequest" not in channel_sources
    assert "AgentResponse" not in channel_sources


def test_channel_turn_forbids_implicit_adapter_state() -> None:
    source = _source("src/qwenpaw/app/channels/turn.py")
    channel_sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in Path("src/qwenpaw/app/channels").rglob("*.py")
    )

    assert "@dataclass(slots=True)" in source
    assert "setattr(request," not in channel_sources
    assert 'getattr(request, "_' not in channel_sources


def test_legacy_runtime_bridges_are_deleted() -> None:
    assert not Path("src/qwenpaw/runtime/channel_request_bridge.py").exists()
    assert not Path("src/qwenpaw/runtime/legacy_reply_adapter.py").exists()
    assert not Path("src/qwenpaw/runtime/request_adapter.py").exists()
    assert not Path("src/qwenpaw/app/channels/reply_presentation.py").exists()
    assert not Path("src/qwenpaw/runtime/reply_projector.py").exists()
    assert not Path("src/qwenpaw/transports/console/envelope.py").exists()
    assert not Path("src/qwenpaw/transports/console/presenter.py").exists()


def test_harness_engine_emits_canonical_events_only() -> None:
    sources = "\n".join(
        _source(path)
        for path in (
            "src/qwenpaw/harnesses/runtime.py",
            "src/qwenpaw/harnesses/session.py",
            "src/qwenpaw/engines/harness.py",
        )
    )

    assert "AgentResponse" not in sources
    assert not Path("src/qwenpaw/harnesses/streaming.py").exists()


def test_task_tracking_is_not_an_sse_transport() -> None:
    source = _source("src/qwenpaw/app/task_tracker.py")

    assert "data: " not in source
    assert "REPLAY_END_SSE" not in source
    assert "TaskEventEncoder" not in _source(
        "src/qwenpaw/app/channels/base.py",
    )
