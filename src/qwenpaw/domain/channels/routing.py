# -*- coding: utf-8 -*-
"""Resolve endpoint-to-agent bindings without transport knowledge."""

from __future__ import annotations

from collections.abc import Iterable

from ..turns.models import RequestSource, RequestSourceKind, TurnRequest
from .models import (
    AgentBinding,
    ChannelEndpoint,
    ChannelRoute,
    InboundMessage,
)


class BindingRouter:
    """Resolve one enabled binding for an inbound endpoint."""

    def __init__(
        self,
        endpoints: Iterable[ChannelEndpoint],
        bindings: Iterable[AgentBinding],
    ) -> None:
        self._endpoints = {
            endpoint.endpoint_id: endpoint for endpoint in endpoints
        }
        self._bindings: dict[str, list[AgentBinding]] = {}
        for binding in bindings:
            self._bindings.setdefault(binding.endpoint_id, []).append(binding)

    def resolve(
        self,
        endpoint_id: str,
        *,
        conversation_id: str,
        agent_hint: str | None = None,
    ) -> ChannelRoute:
        """Resolve an endpoint, rejecting missing or ambiguous bindings."""
        endpoint = self._endpoints.get(endpoint_id)
        if endpoint is None:
            raise LookupError(f"Unknown endpoint: {endpoint_id}")
        if not endpoint.enabled:
            raise LookupError(f"Endpoint is disabled: {endpoint_id}")

        candidates = [
            binding
            for binding in self._bindings.get(endpoint_id, [])
            if binding.enabled
            and (agent_hint is None or binding.agent_id == agent_hint)
        ]
        if not candidates:
            raise LookupError(
                f"No enabled binding for endpoint: {endpoint_id}"
            )
        if len(candidates) > 1:
            raise ValueError(f"Ambiguous endpoint binding: {endpoint_id}")

        binding = candidates[0]
        return ChannelRoute(
            endpoint_id=endpoint_id,
            binding_id=binding.binding_id,
            agent_id=binding.agent_id,
            conversation_id=conversation_id,
        )


def build_turn_request(
    inbound: InboundMessage,
    route: ChannelRoute,
    *,
    turn_id: str,
    session_id: str | None = None,
    source_kind: RequestSourceKind = "channel",
) -> TurnRequest:
    """Build a core request only after an inbound route is resolved."""
    if inbound.endpoint_id != route.endpoint_id:
        raise ValueError(
            f"Inbound endpoint does not match route: "
            f"{inbound.endpoint_id} != {route.endpoint_id}",
        )
    if inbound.conversation_id != route.conversation_id:
        raise ValueError(
            f"Inbound conversation does not match route: "
            f"{inbound.conversation_id} != {route.conversation_id}",
        )

    resolved_session_id = session_id or (
        f"{route.endpoint_id}:{route.conversation_id}"
    )
    return TurnRequest(
        turn_id=turn_id,
        agent_id=route.agent_id,
        session_id=resolved_session_id,
        user_id=inbound.sender_id,
        messages=inbound.content,
        source=RequestSource(
            kind=source_kind,
            endpoint_id=route.endpoint_id,
            binding_id=route.binding_id,
        ),
        reply_target=inbound.reply_target,
        context=inbound.metadata,
    )


__all__ = ["BindingRouter", "build_turn_request"]
