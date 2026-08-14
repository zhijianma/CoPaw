# -*- coding: utf-8 -*-
"""Encode AgentScope events for the Console server-sent event stream."""

from __future__ import annotations

import json
import logging
from typing import Any

from ...agents.context.scroll.serialize import (
    HeadlineDeltaState,
    flush_headline_delta,
    strip_headline,
    strip_headline_delta,
)


logger = logging.getLogger(__name__)


class ConsoleSseEncoder:
    """Serialize one Console response stream without shared mutable state."""

    def __init__(self) -> None:
        self._headline_stream_states: dict[str, Any] = {}

    def encode(self, event: Any) -> str:
        """Encode one event using state scoped to this response stream."""
        return self.encode_event(event, self._headline_stream_states)

    def flush(self, *, msg_id: str | None = None) -> list[str]:
        """Flush incomplete marker prefixes as ordinary content deltas."""
        return self.flush_states(
            self._headline_stream_states,
            msg_id=msg_id,
        )

    @staticmethod
    def sanitize_surrogate_text(text: str) -> str:
        """Replace unpaired Unicode surrogates before UTF-8 output."""
        try:
            text.encode("utf-8")
            return text
        except UnicodeEncodeError:
            return text.encode("utf-8", errors="replace").decode(
                "utf-8",
                errors="replace",
            )

    @classmethod
    def sanitize_for_json(cls, value: Any) -> Any:
        """Sanitize strings nested in JSON-compatible containers."""
        if isinstance(value, str):
            return cls.sanitize_surrogate_text(value)
        if isinstance(value, list):
            return [cls.sanitize_for_json(item) for item in value]
        if isinstance(value, dict):
            output = {}
            for key, item in value.items():
                safe_key = (
                    cls.sanitize_surrogate_text(key)
                    if isinstance(key, str)
                    else key
                )
                output[safe_key] = cls.sanitize_for_json(item)
            return output
        return value

    @staticmethod
    def strip_event_headlines(
        event: Any,
        fallback: str,
        headline_stream_states: dict[str, Any] | None = None,
    ) -> str:
        """Remove internal scroll headlines from a copied event payload."""
        try:
            payload = event.model_dump(mode="json")
        except Exception:  # noqa: BLE001 - preserve fallback behavior
            return fallback

        if (
            headline_stream_states is not None
            and getattr(event, "object", None) == "content"
            and getattr(event, "delta", False)
        ):
            msg_id = str(getattr(event, "msg_id", "") or "")
            index = int(getattr(event, "index", 0) or 0)
            stream_key = f"{msg_id}:{index}"
            raw_text = getattr(event, "text", "") or ""
            state = headline_stream_states.get(
                stream_key,
                HeadlineDeltaState(),
            )
            clean_text, state = strip_headline_delta(raw_text, state=state)
            if isinstance(payload, dict) and "text" in payload:
                payload["text"] = clean_text
            if state.suppressing or state.pending:
                headline_stream_states[stream_key] = state
            else:
                headline_stream_states.pop(stream_key, None)

        def walk(node: Any) -> Any:
            if isinstance(node, str):
                return strip_headline(node)
            if isinstance(node, dict):
                for key, value in list(node.items()):
                    node[key] = walk(value)
                return node
            if isinstance(node, list):
                return [walk(value) for value in node]
            return node

        payload = walk(payload)
        return json.dumps(payload, ensure_ascii=False, default=str)

    @classmethod
    def encode_event(
        cls,
        event: Any,
        headline_stream_states: dict[str, Any] | None = None,
    ) -> str:
        """Encode an event with an optional caller-owned headline state."""
        try:
            if hasattr(event, "model_dump_json"):
                data = event.model_dump_json()
            elif hasattr(event, "json"):
                data = event.json()
            else:
                data = json.dumps({"text": str(event)}, ensure_ascii=True)

            is_tracked_delta = (
                headline_stream_states is not None
                and getattr(event, "object", None) == "content"
                and getattr(event, "delta", False)
            )
            should_strip = (
                "⟦" in data
                or "〚" in data
                or bool(headline_stream_states)
                or is_tracked_delta
            )
            if hasattr(event, "model_dump") and should_strip:
                data = cls.strip_event_headlines(
                    event,
                    data,
                    headline_stream_states,
                )

            return cls.sanitize_surrogate_text(data)
        except Exception as error:  # noqa: BLE001 - safe wire fallback
            logger.warning(
                f"Event JSON serialization failed; using safe fallback: "
                f"{error}",
            )
            try:
                if hasattr(event, "model_dump"):
                    payload = event.model_dump(mode="python")
                elif hasattr(event, "dict"):
                    payload = event.dict()
                else:
                    payload = {"text": str(event)}

                payload = cls.sanitize_for_json(payload)
                return json.dumps(payload, ensure_ascii=True, default=str)
            except Exception as fallback_error:  # noqa: BLE001
                logger.error(
                    f"Fallback event serialization failed: "
                    f"{fallback_error}",
                )
                return json.dumps(
                    {"text": cls.sanitize_surrogate_text(str(event))},
                    ensure_ascii=True,
                )

    @staticmethod
    def flush_states(
        headline_stream_states: dict[str, Any],
        *,
        msg_id: str | None = None,
    ) -> list[str]:
        """Finalize buffered marker prefixes as ordinary content deltas."""
        flushed = []
        for stream_key, state in list(headline_stream_states.items()):
            stream_msg_id, separator, raw_index = stream_key.rpartition(":")
            if not separator:
                stream_msg_id, raw_index = stream_key, "0"
            if msg_id is not None and stream_msg_id != msg_id:
                continue
            headline_stream_states.pop(stream_key, None)
            text = flush_headline_delta(state)
            if not text:
                continue
            try:
                index = int(raw_index)
            except ValueError:
                index = 0
            flushed.append(
                json.dumps(
                    {
                        "object": "content",
                        "delta": True,
                        "msg_id": stream_msg_id,
                        "index": index,
                        "text": text,
                    },
                    ensure_ascii=False,
                ),
            )
        return flushed


__all__ = ["ConsoleSseEncoder"]
