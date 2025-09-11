SHELL := /bin/bash

.PHONY: live-smoke live-bridge live-verify nats-up nats-down

## Run CTP connectivity smoke (no NATS)
live-smoke:
	uv run python scripts/ctp_connect_smoke.py --duration 20 --log-level INFO

## Run LIVE bridge smoke (on_tick → async consume)
live-bridge:
	DURATION_SECONDS=30 uv run python scripts/ctp_bridge_smoke.py

## One-click LIVE → NATS verification (subscriber + ingest)
live-verify:
	./scripts/live_ingest_verify.sh -d 30 -n nats://localhost:4222

## Ensure NATS is running
nats-up:
	docker compose up -d nats

## Stop NATS container
nats-down:
	docker compose rm -f -s -v nats || true
