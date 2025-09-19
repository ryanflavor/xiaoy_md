# Soak Runbook — 1‑Hour Stability Probe (Story 2.4.5)

This runbook describes how to execute a 1‑hour soak test to validate sustained throughput and latency for the live ingest pipeline.

Scope
- Subscriber‑side measurement via NATS probe (no load generation)
- Real market ticks (CTP → Adapter → NATS)
- Outputs rolling MPS and latency; final summary saved to JSON/CSV

Not for CI
- This is an operational procedure for Dev/Stage. Do not run in CI.

## Prerequisites
- NATS reachable (auth or no‑auth)
- Live ingest running with your target `CTP_SYMBOL`
- Python 3.13 with project venv (uv sync)

## Commands
1) Start/ensure live ingest is running (example 60 minutes):

   ```bash
   # Uses .env CTP_*; override NATS via -n as needed
   ./scripts/start_live_ingest.sh -d 3600 -n nats://localhost:4222
   ```

2) Start the probe (5s window, JSON summary):

   ```bash
   # Subscribe to market.tick.> and record a 1-hour summary
   .venv/bin/python scripts/perf/nats_throughput_probe.py \
     --nats-url nats://localhost:4222 \
     --window 5 \
     --format json \
     --out ./logs/soak-probe-summary.json
   ```

3) Optional: CSV summary (useful for spreadsheet analysis):

   ```bash
   .venv/bin/python scripts/perf/nats_throughput_probe.py \
     --nats-url nats://localhost:4222 \
     --window 5 \
     --format csv \
     --out ./logs/soak-probe-summary.csv
   ```

During the run the probe prints periodic window stats; press Ctrl+C to stop and write the summary.

## Success Criteria (Pass/Fail)
- Sustained throughput: average MPS over the full hour ≥ 5,000
- Stability: no probe JSON errors, no timestamp parsing gaps (or < 0.1% of total)
- Connectivity: no sustained NATS disconnects; probe continues to report windows
- Latency: p99 end‑to‑end latency within acceptable envelope for your venue (define target per environment; suggest ≤ 300 ms for Stage)

Suggested evidence to capture
- `logs/soak-probe-summary.json|csv` final summary
- Service logs containing periodic `event=mps_report` to corroborate publisher‑side counters
- NATS exporter metrics (if running with monitoring profile) for independent broker‑side view

## Notes
- The probe performs minimal work per message to avoid becoming a bottleneck.
- If you need to segment the hour by contract or venue, run multiple probes with filtered subjects and aggregate results offline.
