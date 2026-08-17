# -*- coding: utf-8 -*-
"""Encode internal TaskTracker events without a transport dependency."""

from __future__ import annotations

import json
import logging
from typing import Any


logger = logging.getLogger(__name__)


class TaskEventEncoder:
    """Serialize legacy process events for the internal tracker queue."""

    @staticmethod
    def _sanitize_text(text: str) -> str:
        try:
            text.encode("utf-8")
            return text
        except UnicodeEncodeError:
            return text.encode("utf-8", errors="replace").decode(
                "utf-8",
                errors="replace",
            )

    @classmethod
    def _sanitize(cls, value: Any) -> Any:
        if isinstance(value, str):
            return cls._sanitize_text(value)
        if isinstance(value, list):
            return [cls._sanitize(item) for item in value]
        if isinstance(value, dict):
            return {
                cls._sanitize_text(key)
                if isinstance(key, str)
                else key: cls._sanitize(
                    item,
                )
                for key, item in value.items()
            }
        return value

    @classmethod
    def encode(cls, event: Any) -> str:
        """Serialize one event with a UTF-8-safe fallback."""
        try:
            if hasattr(event, "model_dump_json"):
                data = event.model_dump_json()
            elif hasattr(event, "json"):
                data = event.json()
            else:
                data = json.dumps({"text": str(event)}, ensure_ascii=True)
            return cls._sanitize_text(data)
        except Exception as error:  # noqa: BLE001 - internal safe fallback
            logger.warning(f"Task event serialization fallback: {error}")
            if hasattr(event, "model_dump"):
                payload = event.model_dump(mode="python")
            elif hasattr(event, "dict"):
                payload = event.dict()
            else:
                payload = {"text": str(event)}
            return json.dumps(
                cls._sanitize(payload),
                ensure_ascii=True,
                default=str,
            )


__all__ = ["TaskEventEncoder"]
