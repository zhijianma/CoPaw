#!/usr/bin/env python3
"""Compare legacy memory payloads with HintBlock projection payloads."""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import time
import tracemalloc
from pathlib import Path
from typing import Callable

from agentscope.message import DataBlock, Msg, TextBlock, URLSource

from qwenpaw.agents.hints import (
    HINT_POSITION_APPEND_TEXT,
    HINT_SOURCE_BACKGROUND_TOOL,
    HINT_SOURCE_SKILL,
    make_hint_carrier,
)
from qwenpaw.agents.memory.hint_projection import (
    project_messages_for_memory,
)

SAMPLES = 300
WARMUPS = 30
SKILL_HINT = "\n\n<skill>" + ("private instructions\n" * 200) + "</skill>"


def _dump(messages: list[Msg]) -> bytes:
    value = [message.model_dump(mode="json") for message in messages]
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _canonical(messages: list[Msg]) -> bytes:
    """Dump the memory-relevant structure without generated timestamps."""
    values = [message.model_dump(mode="json") for message in messages]

    def clean(value):
        if isinstance(value, list):
            return [clean(item) for item in value]
        if not isinstance(value, dict):
            return value
        ignored = {
            "created_at",
            "error",
            "finished_at",
            "finished_reason",
            "id",
            "structured_output",
            "usage",
        }
        return {
            key: clean(item)
            for key, item in value.items()
            if key not in ignored
        }

    return json.dumps(
        clean(values),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _user(text: str, index: int) -> Msg:
    return Msg(
        id=f"user-{index}",
        name="user",
        role="user",
        content=[TextBlock(id=f"user-text-{index}", text=text)],
    )


def _turn(index: int, *, hints: bool) -> list[Msg]:
    user = _user("typed command", index)
    if not hints:
        return [
            user,
            Msg(
                id=f"assistant-{index}",
                name="agent",
                role="assistant",
                content=[TextBlock(text="answer")],
            ),
        ]
    skill = make_hint_carrier(
        hint=SKILL_HINT,
        source=HINT_SOURCE_SKILL,
        target_msg_id=user.id,
        position=HINT_POSITION_APPEND_TEXT,
    )
    background = make_hint_carrier(
        hint="<system-reminder>background result</system-reminder>",
        source=HINT_SOURCE_BACKGROUND_TOOL,
    )
    return [user, skill, background]


def _legacy_turn(index: int, *, hints: bool) -> list[Msg]:
    text = "typed command"
    if hints:
        text += SKILL_HINT
    messages = [_user(text, index)]
    if hints:
        messages.append(
            Msg(
                name="system",
                role="assistant",
                content=[
                    TextBlock(
                        text=(
                            "<system-reminder>background result"
                            "</system-reminder>"
                        ),
                    ),
                ],
            ),
        )
    else:
        messages.append(
            Msg(
                id=f"assistant-{index}",
                name="agent",
                role="assistant",
                content=[TextBlock(text="answer")],
            ),
        )
    return messages


def _multimodal_pair(count: int) -> tuple[list[Msg], list[Msg]]:
    legacy: list[Msg] = []
    migrated: list[Msg] = []
    for index in range(count):
        blocks = [
            TextBlock(text=f"result-{index}"),
            DataBlock(
                name=f"image-{index}.png",
                source=URLSource(
                    url=f"https://example.invalid/{index}.png",
                    media_type="image/png",
                ),
            ),
            DataBlock(
                name=f"file-{index}.pdf",
                source=URLSource(
                    url=f"https://example.invalid/{index}.pdf",
                    media_type="application/pdf",
                ),
            ),
        ]
        legacy.append(
            Msg(name="system", role="assistant", content=blocks),
        )
        migrated.append(
            make_hint_carrier(
                hint=blocks,
                source=HINT_SOURCE_BACKGROUND_TOOL,
            ),
        )
    return legacy, migrated


def _scenario(turns: int, *, hints: bool) -> tuple[list[Msg], list[Msg]]:
    legacy: list[Msg] = []
    migrated: list[Msg] = []
    for index in range(turns):
        legacy.extend(_legacy_turn(index, hints=hints))
        migrated.extend(_turn(index, hints=hints))
    return legacy, migrated


def _measure(operation: Callable[[], bytes]) -> dict[str, float | int]:
    for _ in range(WARMUPS):
        operation()
    timings: list[int] = []
    for _ in range(SAMPLES):
        started = time.perf_counter_ns()
        operation()
        timings.append(time.perf_counter_ns() - started)
    tracemalloc.start()
    payload = operation()
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    timings.sort()
    p95_index = min(len(timings) - 1, int(len(timings) * 0.95))
    return {
        "p50_ms": statistics.median(timings) / 1_000_000,
        "p95_ms": timings[p95_index] / 1_000_000,
        "peak_bytes": peak,
        "payload_bytes": len(payload),
    }


def _token_estimate(messages: list[Msg]) -> int:
    chars = sum(len(message.get_text_content() or "") for message in messages)
    return int(chars / 4 + 0.5)


def run() -> tuple[dict, dict, str]:
    scenarios = {
        "no_hint": _scenario(4, hints=False),
        "typical_turn": _scenario(2, hints=True),
        "batched_100": _scenario(34, hints=True),
        "proactive_1000": _scenario(334, hints=True),
        "multimodal": _multimodal_pair(20),
    }
    before: dict = {"environment": _environment(), "scenarios": {}}
    after: dict = {"environment": _environment(), "scenarios": {}}
    lines = [
        "# HintBlock migration benchmark",
        "",
        "| Scenario | Before p95 | After p95 | Overhead | Effective equal |",
        "|---|---:|---:|---:|---|",
    ]
    for name, (legacy, migrated) in scenarios.items():
        before_result = _measure(lambda value=legacy: _dump(value))
        after_result = _measure(
            lambda value=migrated: _dump(
                project_messages_for_memory(value),
            ),
        )
        projected = project_messages_for_memory(migrated)
        payload_equal = _canonical(legacy) == _canonical(projected)
        before_result["token_estimate"] = _token_estimate(legacy)
        after_result["token_estimate"] = _token_estimate(projected)
        after_result["live_session_bytes"] = len(_dump(migrated))
        after_result["session_growth_pct"] = (
            (
                after_result["live_session_bytes"]
                - before_result["payload_bytes"]
            )
            / before_result["payload_bytes"]
            * 100
        )
        after_result["payload_equal"] = payload_equal
        before["scenarios"][name] = before_result
        after["scenarios"][name] = after_result
        overhead = after_result["p95_ms"] - before_result["p95_ms"]
        lines.append(
            f"| {name} | {before_result['p95_ms']:.3f} ms | "
            f"{after_result['p95_ms']:.3f} ms | {overhead:.3f} ms | "
            f"{'yes' if payload_equal else 'no'} |"
        )
    lines.extend(
        [
            "",
            f"Samples per operation: {SAMPLES}; warmups: {WARMUPS}.",
            "",
            "## Acceptance gates",
            "",
            _gate_lines(before, after),
        ],
    )
    return before, after, "\n".join(lines) + "\n"


def _gate_lines(before: dict, after: dict) -> str:
    no_hint = after["scenarios"]["no_hint"]
    no_hint_before = before["scenarios"]["no_hint"]
    typical = after["scenarios"]["typical_turn"]
    batch = after["scenarios"]["batched_100"]
    gates = [
        (
            "No-hint p95 overhead <= 0.1 ms",
            no_hint["p95_ms"] - no_hint_before["p95_ms"] <= 0.1,
        ),
        ("Typical projection p95 <= 2 ms", typical["p95_ms"] <= 2),
        ("100-message p95 <= 20 ms", batch["p95_ms"] <= 20),
        (
            "Typical live-session growth <= 15%",
            typical["session_growth_pct"] <= 15,
        ),
        (
            "Projected token estimate unchanged",
            all(
                after["scenarios"][name]["token_estimate"]
                == before["scenarios"][name]["token_estimate"]
                for name in before["scenarios"]
            ),
        ),
        (
            "Effective memory payloads equal",
            all(
                result["payload_equal"]
                for result in after["scenarios"].values()
            ),
        ),
    ]
    return "\n".join(
        f"- {'PASS' if passed else 'FAIL'}: {label}" for label, passed in gates
    )


def _environment() -> dict[str, str | int]:
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "samples": SAMPLES,
        "warmups": WARMUPS,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    before, after, comparison = run()
    if args.output_dir is None:
        print(comparison, end="")
        return
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, payload in (("before.json", before), ("after.json", after)):
        (args.output_dir / name).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    (args.output_dir / "comparison.md").write_text(
        comparison,
        encoding="utf-8",
    )
    print(comparison, end="")


if __name__ == "__main__":
    main()
