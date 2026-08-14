# -*- coding: utf-8 -*-
# pylint: disable=unused-import
"""Compatibility imports for the Console envelope implementation."""

from ..transports.console.envelope import (
    Envelope,
    _propagate_event_metadata,
)


__all__ = ["Envelope"]
