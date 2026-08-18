# -*- coding: utf-8 -*-
"""Connectivity and framing ports; transports do not own semantics."""

from __future__ import annotations

from typing import Any, Protocol


class TransportEncoder(Protocol):
    """Serialize one protocol-native frame for a concrete connection."""

    def encode(self, frame: Any) -> str | bytes:
        """Encode one frame without interpreting runtime semantics."""


__all__ = ["TransportEncoder"]
