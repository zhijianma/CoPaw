# -*- coding: utf-8 -*-
"""Map provider-neutral harness events into canonical runtime events."""

from __future__ import annotations

import json
import uuid

from ..domain.turns.events import RuntimeEvent, RuntimeEventType
from ..harnesses.events import HarnessEvent, HarnessEventKind


class HarnessRuntimeEventMapper:
    """Stateful engine-boundary mapper with no presentation dependency."""

    def __init__(self, turn_id: str) -> None:
        self._turn_id = turn_id
        self._content_kind = ""
        self._block_id = ""
        self._tool_output: dict[str, str] = {}

    def map(self, event: HarnessEvent) -> list[RuntimeEvent]:
        """Translate one provider event into zero or more runtime facts."""
        if event.kind is HarnessEventKind.TEXT_DELTA:
            return self._content_delta("text", event.text)
        if event.kind is HarnessEventKind.REASONING_DELTA:
            return self._content_delta("reasoning", event.text)
        if event.kind is HarnessEventKind.TOOL_STARTED:
            result = self.finish_content()
            call_id = event.item_id or uuid.uuid4().hex
            arguments = json.dumps(
                event.data.get("arguments") or {},
                ensure_ascii=False,
                default=str,
            )
            result.extend(
                [
                    self._event(
                        RuntimeEventType.TOOL_CALL_STARTED,
                        tool_call_id=call_id,
                        name=event.tool_name or "tool",
                    ),
                    self._event(
                        RuntimeEventType.TOOL_CALL_DELTA,
                        tool_call_id=call_id,
                        delta=arguments,
                    ),
                    self._event(
                        RuntimeEventType.TOOL_CALL_COMPLETED,
                        tool_call_id=call_id,
                    ),
                    self._event(
                        RuntimeEventType.TOOL_RESULT_STARTED,
                        tool_call_id=call_id,
                        name=event.tool_name or "tool",
                    ),
                ],
            )
            self._tool_output[call_id] = ""
            return result
        if event.kind is HarnessEventKind.TOOL_PROGRESS:
            call_id = event.item_id
            self._tool_output[call_id] = (
                self._tool_output.get(call_id, "") + event.text
            )
            if not event.text:
                return []
            return [
                self._event(
                    RuntimeEventType.TOOL_RESULT_DELTA,
                    tool_call_id=call_id,
                    content_kind="text",
                    delta=event.text,
                ),
            ]
        if event.kind is HarnessEventKind.TOOL_COMPLETED:
            call_id = event.item_id
            previous = self._tool_output.pop(call_id, "")
            result: list[RuntimeEvent] = []
            if event.text and event.text != previous:
                result.append(
                    self._event(
                        RuntimeEventType.TOOL_RESULT_DELTA,
                        tool_call_id=call_id,
                        content_kind="text",
                        delta=event.text,
                    ),
                )
            result.append(
                self._event(
                    RuntimeEventType.TOOL_RESULT_COMPLETED,
                    tool_call_id=call_id,
                    name=event.tool_name or "tool",
                    output=event.text or previous,
                    **{
                        key: value
                        for key, value in event.data.items()
                        if key != "arguments"
                    },
                ),
            )
            return result
        return []

    def finish_content(self) -> list[RuntimeEvent]:
        """Close the current text or reasoning block, if any."""
        if not self._block_id:
            return []
        event = self._event(
            RuntimeEventType.CONTENT_COMPLETED,
            content_kind=self._content_kind,
            block_id=self._block_id,
        )
        self._content_kind = ""
        self._block_id = ""
        return [event]

    def _content_delta(self, kind: str, text: str) -> list[RuntimeEvent]:
        result: list[RuntimeEvent] = []
        if self._content_kind != kind:
            result.extend(self.finish_content())
            self._content_kind = kind
            self._block_id = f"{kind}_{uuid.uuid4().hex}"
            result.append(
                self._event(
                    RuntimeEventType.CONTENT_STARTED,
                    content_kind=kind,
                    block_id=self._block_id,
                ),
            )
        if text:
            result.append(
                self._event(
                    RuntimeEventType.CONTENT_DELTA,
                    content_kind=kind,
                    block_id=self._block_id,
                    delta=text,
                ),
            )
        return result

    def _event(self, event_type: RuntimeEventType, **data: object) -> RuntimeEvent:
        return RuntimeEvent.canonical(
            event_type,
            turn_id=self._turn_id,
            data=data,
        )


__all__ = ["HarnessRuntimeEventMapper"]
