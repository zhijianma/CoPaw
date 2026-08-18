# -*- coding: utf-8 -*-
"""Console request decoding stays outside Runtime orchestration."""

from qwenpaw.protocols.builtins import get_protocol_registry
from qwenpaw.schemas import AgentRequest


def test_console_ingress_decodes_existing_api_request() -> None:
    native = AgentRequest(
        session_id="session-1",
        user_id="user-1",
        agent_id="agent-1",
        input=[],
    )
    native.id = "turn-1"

    request = get_protocol_registry().create_ingress("console").decode(native)

    assert request.turn_id == "turn-1"
    assert request.agent_id == "agent-1"
    assert request.session_id == "session-1"
    assert request.source.protocol == "console"
