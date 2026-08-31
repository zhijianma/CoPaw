# HintBlock migration benchmark

| Scenario | Before p95 | After p95 | Overhead | Effective equal |
|---|---:|---:|---:|---|
| no_hint | 0.031 ms | 0.037 ms | 0.006 ms | yes |
| typical_turn | 0.040 ms | 0.150 ms | 0.110 ms | yes |
| batched_100 | 0.845 ms | 2.601 ms | 1.756 ms | yes |
| proactive_1000 | 7.354 ms | 69.341 ms | 61.987 ms | yes |
| multimodal | 0.254 ms | 0.907 ms | 0.653 ms | yes |

Samples per operation: 300; warmups: 30.

## Acceptance gates

- PASS: No-hint p95 overhead <= 0.1 ms
- PASS: Typical projection p95 <= 2 ms
- PASS: 100-message p95 <= 20 ms
- PASS: Typical live-session growth <= 15%
- PASS: Projected token estimate unchanged
- PASS: Effective memory payloads equal
