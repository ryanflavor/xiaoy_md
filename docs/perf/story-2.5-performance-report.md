# Story 2.5 — Live Throughput Validation Report

## Run Metadata
- Date: _Pending live execution_
- Operator: _Pending assignment_
- Environment: _Set to live profile (docker compose --profile live)_
- Control plane tooling: `uv run python scripts/operations/full_feed_subscription.py --batch-size 500 --rate-limit-max 5000 --rate-limit-window 60`
- Soak tooling: `uv run python scripts/perf/nats_throughput_probe.py --nats-url <url> --window 5 --format json --out logs/soak/story-2.5-summary.json`

## Contract Discovery
- Trigger `md.contracts.list` via orchestration script; artifacts written to `logs/operations/full-feed-YYYYMMDD-HHMMSS/contracts.json`.
- Ensure `source` is `vnpy` on first live run; subsequent requests should read from cache.
- Confirm collected symbol count matches venue reference list (vt_symbol canonical form).

## Bulk Subscription Workflow
- Override live rate limit using `SUBSCRIBE_RATE_LIMIT_MAX_REQUESTS`/`SUBSCRIBE_RATE_LIMIT_WINDOW_SECONDS` to prevent throttling during initial blast.
- Script batches symbols and records each response under `logs/operations/full-feed-*/batch-XYZ.json` with accepted/rejected breakdown.
- Expected outcome: zero actionable rejections; any invalid symbols logged in `rejections.json` for remediation before soak.

## 1-Hour Soak Summary (Pending)
| Metric | Target | Observed | Evidence |
| --- | --- | --- | --- |
| Average MPS | ≥ 5,000 | _Pending_ | `logs/soak/story-2.5-summary.json` |
| Peak MPS (window) | Track | _Pending_ | `logs/soak/story-2.5-summary.json` |
| Probe JSON errors | 0 | _Pending_ | Probe summary |
| Service `mps_report` parity | ✓ | _Pending_ | `logs/market-data-service.log` |
| Latency p99 | ≤ 300 ms | _Pending_ | Probe summary |

## Observability Checklist
- Capture `event=mps_report` entries from `market-data-service` logs throughout the soak.
- Store probe JSON/CSV outputs plus relevant Grafana/NATS metrics snapshots.
- Correlate any drops or disconnects with `nats_throughput_probe` logs and service counters.

## Follow-ups
- File remediation tickets if `rejections.json` contains persistent failures (invalid symbol, configuration gap).
- Document retry/backoff adjustments when rate-limit warnings appear in service logs.
- Update this report with actual soak metrics and embed artifact paths once live validation completes.
