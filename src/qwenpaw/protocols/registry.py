# -*- coding: utf-8 -*-
"""Protocol extension registry."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Callable, Mapping

from .ports import PresentationContext, TurnEventPresenter, TurnIngress

PresenterFactory = Callable[[PresentationContext], TurnEventPresenter]
IngressFactory = Callable[..., TurnIngress]


@dataclass(frozen=True, slots=True)
class ProtocolRegistration:
    """All factories and metadata belonging to one semantic protocol."""

    key: str
    presenter_factory: PresenterFactory
    ingress_factory: IngressFactory | None = None
    config_model: type[Any] | None = None
    capabilities: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        key = self.key.strip().lower()
        if not key:
            raise ValueError("protocol key must not be empty")
        object.__setattr__(self, "key", key)
        object.__setattr__(
            self,
            "capabilities",
            MappingProxyType(dict(self.capabilities)),
        )


class ProtocolRegistry:
    """Resolve protocol ports without hardcoding them in Runtime."""

    def __init__(self) -> None:
        self._registrations: dict[str, ProtocolRegistration] = {}

    def register(self, registration: ProtocolRegistration) -> None:
        """Register one protocol, rejecting ambiguous ownership."""
        if registration.key in self._registrations:
            raise ValueError(
                f"Protocol already registered: {registration.key}",
            )
        self._registrations[registration.key] = registration

    def get(self, key: str) -> ProtocolRegistration:
        """Return one registration by normalized key."""
        normalized = key.strip().lower()
        try:
            return self._registrations[normalized]
        except KeyError as error:
            raise KeyError(f"Unknown protocol: {normalized}") from error

    def create_presenter(
        self,
        context: PresentationContext,
    ) -> TurnEventPresenter:
        """Create a presenter scoped to one conversation."""
        return self.get(context.protocol).presenter_factory(context)

    def create_ingress(self, key: str, **kwargs: Any) -> TurnIngress:
        """Create the configured ingress decoder for a protocol."""
        registration = self.get(key)
        if registration.ingress_factory is None:
            raise ValueError(f"Protocol has no ingress: {registration.key}")
        return registration.ingress_factory(**kwargs)


__all__ = ["ProtocolRegistration", "ProtocolRegistry"]
