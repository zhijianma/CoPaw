# -*- coding: utf-8 -*-
"""Existing WebUI Console semantic protocol."""

from .ingress import ConsoleTurnIngress
from .presenter import ConsoleEventPresenter

__all__ = ["ConsoleEventPresenter", "ConsoleTurnIngress"]
