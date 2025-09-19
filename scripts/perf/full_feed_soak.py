#!/usr/bin/env python3
"""Full-feed NATS soak with detailed stats (1h by default).

Subscribes to ``market.tick.>`` and records:
- Total messages, avg MPS, last-window MPS
- MPS timeseries (per-second, rolling window)
- Unique subjects (exchange.symbol) count
- Per-exchange counts + top subjects (CSV)
- Latency stats (min/mean/p50/p90/p99/max) via reservoir sampling
- JSON errors and missing timestamp counts

Usage examples::

    uv run python scripts/perf/full_feed_soak.py \
        --nats-url nats://127.0.0.1:4222 \
        --user "$NATS_USER" --password "$NATS_PASSWORD" \
        --duration 3600 --window 5 --out-dir logs/soak

Output files (in a timestamped directory under ``--out-dir``)::

    summary.json                High-level run metrics and latency summary
    mps_timeseries.csv          ISO time, mps (rolling window)
    top_subjects.csv            subject,count (sorted desc, limited by --top-n)
    per_exchange.json           {"EX": count, ...}
    latency_samples.csv         Reservoir sample of latencies in ms (optional)
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter, deque
import contextlib
import csv
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import random
from typing import Any

SUBJECT_PREFIX = "market.tick."
SUBJECT_EX_INDEX = 2
SUBJECT_SYMBOL_INDEX = 3


def _parse_iso_dt(value: str) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
    except (ValueError, TypeError):
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


@dataclass(slots=True)
class LatencyStats:
    count: int = 0
    min_ms: float | None = None
    max_ms: float | None = None
    sum_ms: float = 0.0

    def add(self, ms: float) -> None:
        self.count += 1
        self.sum_ms += ms
        self.min_ms = ms if self.min_ms is None else min(self.min_ms, ms)
        self.max_ms = ms if self.max_ms is None else max(self.max_ms, ms)

    @property
    def mean_ms(self) -> float | None:
        return (self.sum_ms / self.count) if self.count else None


def _percentiles(values: list[float], pts: list[float]) -> list[float]:
    if not values:
        return [0.0 for _ in pts]
    arr = sorted(values)
    n = len(arr)
    output: list[float] = []
    for p in pts:
        q = max(0.0, min(100.0, float(p))) / 100.0
        idx = q * (n - 1)
        lo = int(idx)
        hi = min(lo + 1, n - 1)
        frac = idx - lo
        val = arr[lo] * (1.0 - frac) + arr[hi] * frac
        output.append(val)
    return output


def _subject_parts(subject: str) -> tuple[str | None, str | None]:
    if not subject.startswith(SUBJECT_PREFIX):
        return None, None
    parts = subject.split(".")
    if len(parts) <= SUBJECT_EX_INDEX:
        return None, None
    exchange = parts[SUBJECT_EX_INDEX]
    symbol = parts[SUBJECT_SYMBOL_INDEX] if len(parts) > SUBJECT_SYMBOL_INDEX else None
    return exchange, symbol


def _now_utc_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(slots=True)
class SoakConfig:
    nats_url: str
    subject: str = "market.tick.>"
    user: str | None = None
    password: str | None = None
    duration: int = 3600
    window: float = 5.0
    out_dir: Path = Path("logs/soak")
    top_n: int = 2000
    latency_sample_size: int = 100_000
    verbose: bool = False


@dataclass(slots=True)
class SoakState:
    ts_window: deque[float] = field(default_factory=deque)
    mps_series: list[tuple[str, float]] = field(default_factory=list)
    by_subject: Counter[str] = field(default_factory=Counter)
    by_exchange: Counter[str] = field(default_factory=Counter)
    total: int = 0
    json_errors: int = 0
    missing_timestamp: int = 0
    latency_stats: LatencyStats = field(default_factory=LatencyStats)
    latency_sample: list[float] = field(default_factory=list)


@dataclass(slots=True)
class IngestContext:
    window: float
    sample_cap: int
    rng: random.Random


async def run_soak(cfg: SoakConfig) -> Path:
    from nats.aio.client import Client as NatsClient

    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = cfg.out_dir / f"full-feed-soak-{stamp}"
    run_dir.mkdir(parents=True, exist_ok=False)

    loop = asyncio.get_running_loop()
    state = SoakState()
    ctx = IngestContext(
        window=cfg.window,
        sample_cap=max(0, int(cfg.latency_sample_size)),
        rng=random.Random(0xBEEF),
    )

    nc = await _connect_nats(cfg, NatsClient)

    async def cb(msg):  # type: ignore[no-untyped-def]
        _ingest_tick(msg, state, loop, ctx)

    sub = await nc.subscribe(cfg.subject, cb=cb)

    reporter_task = asyncio.create_task(_reporter_loop(loop, cfg, state))

    try:
        await asyncio.sleep(cfg.duration)
    finally:
        await _shutdown_nats(nc, sub, reporter_task)

    summary = _build_summary(cfg, state)
    _write_soak_outputs(run_dir, cfg, state, summary, ctx.sample_cap)

    return run_dir


async def _connect_nats(
    cfg: SoakConfig, client_cls: type
) -> Any:  # pragma: no cover - thin connector
    client = client_cls()
    options: dict[str, Any] = {
        "servers": [cfg.nats_url],
        "name": "full-feed-soak",
    }
    if cfg.user and cfg.password:
        options.update({"user": cfg.user, "password": cfg.password})
    await client.connect(**options)
    return client


async def _reporter_loop(
    loop: asyncio.AbstractEventLoop, cfg: SoakConfig, state: SoakState
) -> None:
    while True:
        await asyncio.sleep(1.0)
        _record_mps_snapshot(state, loop, cfg)
        if cfg.verbose and state.mps_series:
            timestamp, mps = state.mps_series[-1]
            print(json.dumps({"timestamp": timestamp, "mps": mps}))


async def _shutdown_nats(
    client: Any, subscription: Any, reporter_task: asyncio.Task
) -> None:
    reporter_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await reporter_task
    with contextlib.suppress(Exception):
        await subscription.unsubscribe()
    with contextlib.suppress(Exception):
        await client.drain()
    with contextlib.suppress(Exception):
        await client.close()


def _ingest_tick(
    msg: Any,
    state: SoakState,
    loop: asyncio.AbstractEventLoop,
    ctx: IngestContext,
) -> None:
    now_mono = loop.time()
    state.ts_window.append(now_mono)
    cutoff = now_mono - ctx.window
    while state.ts_window and state.ts_window[0] < cutoff:
        state.ts_window.popleft()

    state.total += 1
    state.by_subject[msg.subject] += 1
    exchange, _ = _subject_parts(msg.subject)
    if exchange:
        state.by_exchange[exchange] += 1

    try:
        payload = json.loads(msg.data.decode() or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        state.json_errors += 1
        return

    timestamp_text = payload.get("timestamp") if isinstance(payload, dict) else None
    if not isinstance(timestamp_text, str):
        state.missing_timestamp += 1
        return

    dt = _parse_iso_dt(timestamp_text)
    if dt is None:
        state.missing_timestamp += 1
        return

    ms = max(0.0, (datetime.now(UTC) - dt.astimezone(UTC)).total_seconds() * 1000.0)
    state.latency_stats.add(ms)
    if ctx.sample_cap == 0:
        return

    if len(state.latency_sample) < ctx.sample_cap:
        state.latency_sample.append(ms)
    else:
        idx = ctx.rng.randint(0, state.latency_stats.count - 1)
        if idx < ctx.sample_cap:
            state.latency_sample[idx] = ms


def _record_mps_snapshot(
    state: SoakState, loop: asyncio.AbstractEventLoop, cfg: SoakConfig
) -> None:
    cutoff = loop.time() - cfg.window
    while state.ts_window and state.ts_window[0] < cutoff:
        state.ts_window.popleft()
    mps = len(state.ts_window) / cfg.window if cfg.window > 0 else 0.0
    state.mps_series.append((_now_utc_iso(), mps))


def _build_summary(cfg: SoakConfig, state: SoakState) -> dict[str, Any]:
    percentiles = (
        _percentiles(state.latency_sample, [50, 90, 99])
        if state.latency_sample
        else [0.0, 0.0, 0.0]
    )
    return {
        "run_seconds": cfg.duration,
        "window_seconds": cfg.window,
        "total_messages": state.total,
        "avg_mps": (state.total / cfg.duration) if cfg.duration > 0 else 0.0,
        "last_window_mps": (state.mps_series[-1][1] if state.mps_series else 0.0),
        "unique_subjects": len(state.by_subject),
        "per_exchange": dict(sorted(state.by_exchange.items())),
        "latency_ms": {
            "count": state.latency_stats.count,
            "min": (
                None
                if state.latency_stats.min_ms is None
                else round(state.latency_stats.min_ms, 2)
            ),
            "mean": (
                None
                if state.latency_stats.mean_ms is None
                else round(state.latency_stats.mean_ms, 2)
            ),
            "p50": round(percentiles[0], 2),
            "p90": round(percentiles[1], 2),
            "p99": round(percentiles[2], 2),
            "max": (
                None
                if state.latency_stats.max_ms is None
                else round(state.latency_stats.max_ms, 2)
            ),
        },
        "json_errors": state.json_errors,
        "missing_timestamp": state.missing_timestamp,
        "time_utc": _now_utc_iso(),
    }


def _write_soak_outputs(
    run_dir: Path,
    cfg: SoakConfig,
    state: SoakState,
    summary: dict[str, Any],
    sample_cap: int,
) -> None:
    (run_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    with (run_dir / "mps_timeseries.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["timestamp", "mps"])
        writer.writerows(state.mps_series)

    top_subjects = state.by_subject.most_common(max(1, int(cfg.top_n)))
    with (run_dir / "top_subjects.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["subject", "count"])
        writer.writerows(top_subjects)

    (run_dir / "per_exchange.json").write_text(
        json.dumps(
            dict(sorted(state.by_exchange.items())), ensure_ascii=False, indent=2
        ),
        encoding="utf-8",
    )

    if sample_cap > 0 and state.latency_sample:
        with (run_dir / "latency_samples.csv").open(
            "w", encoding="utf-8", newline=""
        ) as fh:
            writer = csv.writer(fh)
            writer.writerow(["latency_ms"])
            writer.writerows([[f"{value:.3f}"] for value in state.latency_sample])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Full-feed NATS soak with detailed stats"
    )
    parser.add_argument(
        "--nats-url", default=os.getenv("NATS_URL", "nats://127.0.0.1:4222")
    )
    parser.add_argument("--user", default=os.getenv("NATS_USER"))
    parser.add_argument("--password", default=os.getenv("NATS_PASSWORD"))
    parser.add_argument(
        "--duration", type=int, default=3600, help="Seconds to run (default 3600)"
    )
    parser.add_argument(
        "--window", type=float, default=5.0, help="Rolling MPS window seconds"
    )
    parser.add_argument("--out-dir", default="logs/soak", help="Base output directory")
    parser.add_argument(
        "--top-n", type=int, default=2000, help="Rows to keep in top_subjects.csv"
    )
    parser.add_argument(
        "--latency-sample-size",
        type=int,
        default=100_000,
        help="Reservoir sample size for latency percentiles",
    )
    parser.add_argument("--subject", default="market.tick.>")
    parser.add_argument(
        "--verbose", action="store_true", help="Print per-second window stats"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = SoakConfig(
        nats_url=args.nats_url,
        subject=args.subject,
        user=args.user,
        password=args.password,
        duration=int(args.duration),
        window=float(args.window),
        out_dir=Path(args.out_dir),
        top_n=int(args.top_n),
        latency_sample_size=int(args.latency_sample_size),
        verbose=bool(args.verbose),
    )

    if config.verbose:
        cfg_dict = asdict(config)
        cfg_dict["out_dir"] = str(config.out_dir)
        print(json.dumps(cfg_dict, ensure_ascii=False, indent=2))

    try:
        run_dir = asyncio.run(run_soak(config))
    except KeyboardInterrupt:
        return 130
    print(str(run_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
