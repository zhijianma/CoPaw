# -*- coding: utf-8 -*-
"""Transport-neutral AgentScope execution driver."""

from __future__ import annotations

import logging
from typing import Any, AsyncGenerator

from ..domain.turns.events import RuntimeEvent
from ..engines.agentscope import AgentScopeEventNormalizer
from .heartbeat import (
    _iter_with_heartbeat,
    _HEARTBEAT_TICK,
    HEARTBEAT_INTERVAL_SECONDS,
)

logger = logging.getLogger(__name__)


class AgentExecutor:
    """Execute an agent reply stream and emit runtime events.

    One instance per ``Runtime.run()`` invocation.  The executor owns the
    heartbeat wrapper but not the agent itself (that belongs to the
    ``HookContext``).
    """

    def __init__(self, agent: Any, *, turn_id: str = "") -> None:
        self._agent = agent
        self._turn_id = turn_id
        self._normalizer = AgentScopeEventNormalizer()

    async def run(
        self,
        msgs: list[Any],
    ) -> AsyncGenerator[RuntimeEvent, None]:
        """Drive ``agent.reply_stream`` and yield runtime events.

        Wraps the raw event stream with ``_iter_with_heartbeat`` so long
        idle periods still surface transport-neutral heartbeat events.
        """
        agent_iter = self._agent.reply_stream(inputs=msgs).__aiter__()
        async for event in _iter_with_heartbeat(
            agent_iter,
            HEARTBEAT_INTERVAL_SECONDS,
        ):
            if event is _HEARTBEAT_TICK:
                yield RuntimeEvent.heartbeat(turn_id=self._turn_id)
                continue

            yield self._normalizer.normalize(
                event,
                turn_id=self._turn_id,
            )


__all__ = ["AgentExecutor"]
