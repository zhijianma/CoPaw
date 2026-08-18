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
    source = _source("src/qwenpaw/transports/console/envelope.py")

    assert "agentscope.event" not in source.lower()


def test_request_source_accepts_protocol_extensions() -> None:
    source = RequestSource(protocol="future-protocol", endpoint_id="edge-1")

    assert source.protocol == "future-protocol"
    assert source.endpoint_id == "edge-1"
