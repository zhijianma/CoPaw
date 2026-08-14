# -*- coding: utf-8 -*-
"""Console SSE encoder contracts."""

from __future__ import annotations

import json

import pytest

from qwenpaw.transports.console.sse import ConsoleSseEncoder


class _FakeDumpEvent:
    def __init__(self, payload):
        self._payload = payload
        for key, value in payload.items():
            setattr(self, key, value)

    def model_dump(self, mode="json"):
        del mode
        return self._payload

    def model_dump_json(self):
        return json.dumps(self._payload, ensure_ascii=True)


def test_encoder_preserves_plain_event_json() -> None:
    event = _FakeDumpEvent(
        {
            "object": "content",
            "delta": True,
            "msg_id": "message-1",
            "index": 0,
            "text": "hello",
        },
    )

    assert ConsoleSseEncoder().encode(event) == event.model_dump_json()


def test_encoder_hides_split_headline_across_events() -> None:
    encoder = ConsoleSseEncoder()
    chunks = (
        "answer\n<!",
        "-- ⟦ internal status",
        " | anchors: TC-1 ⟧ -->",
    )

    visible = []
    for text in chunks:
        event = _FakeDumpEvent(
            {
                "object": "content",
                "delta": True,
                "msg_id": "message-1",
                "index": 0,
                "text": text,
            },
        )
        visible.append(json.loads(encoder.encode(event))["text"])

    assert "".join(visible) == "answer\n"
    assert not encoder.flush()


@pytest.mark.parametrize("suffix", ("<", "<!", "<!--"))
def test_encoder_flushes_unconfirmed_marker_prefix(suffix: str) -> None:
    encoder = ConsoleSseEncoder()
    event = _FakeDumpEvent(
        {
            "object": "content",
            "delta": True,
            "msg_id": "message-1",
            "index": 2,
            "text": f"ordinary comparison ends in {suffix}",
        },
    )

    encoded = encoder.encode(event)
    flushed = encoder.flush(msg_id="message-1")

    assert json.loads(encoded)["text"] == "ordinary comparison ends in "
    assert [json.loads(item)["text"] for item in flushed] == [suffix]
    assert json.loads(flushed[0])["index"] == 2


def test_encoder_replaces_unpaired_unicode_surrogate() -> None:
    event = _FakeDumpEvent({"object": "content", "text": "bad\ud800text"})

    encoded = ConsoleSseEncoder().encode(event)

    assert "bad" in encoded
    assert "text" in encoded
    encoded.encode("utf-8")


def test_encoder_safe_fallback_handles_non_json_value() -> None:
    value = object()

    class _FallbackEvent:
        def model_dump_json(self):
            raise TypeError("cannot serialize")

        def model_dump(self, mode="python"):
            del mode
            return {"value": value}

    encoded = ConsoleSseEncoder().encode(_FallbackEvent())

    assert json.loads(encoded) == {"value": str(value)}
