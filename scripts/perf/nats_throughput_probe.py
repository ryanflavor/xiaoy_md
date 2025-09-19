#!/usr/bin/env python3
"""NATS throughput & latency probe."""

from __future__ import annotations

import argparse
import asyncio
from collections import deque
import contextlib
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import signal
from typing import Any


def _parse_iso_dt(value: str) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _percentiles(values: list[float], points: list[float]) -> list[float]:
    if not values:
        return [0.0 for _ in points]
    arr = sorted(values)
    n = len(arr)
    output: list[float] = []
    for p in points:
        if n == 1:
            output.append(arr[0])
            continue
        q = max(0.0, min(100.0, float(p))) / 100.0
        idx = q * (n - 1)
        lo = int(idx)
        hi = min(lo + 1, n - 1)
        frac = idx - lo
        output.append(arr[lo] * (1.0 - frac) + arr[hi] * frac)
    return output


@dataclass(slots=True)
class Summary:
    run_seconds: float
    window_seconds: float
    total_messages: int
    avg_mps: float
    last_mps: float
    latency_ms_min: float | None
    latency_ms_mean: float | None
    latency_ms_p50: float | None
    latency_ms_p90: float | None
    latency_ms_p99: float | None
    latency_ms_max: float | None
    json_errors: int
    no_timestamp: int


@dataclass(slots=True)
class ProbeConfig:
    nats_url: str
    window: float
    out_format: str
    out_path: str | None
    user: str | None = None
    password: str | None = None


@dataclass(slots=True)
class ProbeState:
    ts_window: deque[float]
    lat_window: deque[tuple[float, float]]
    latencies: list[float]
    total: int = 0
    json_errors: int = 0
    missing_ts: int = 0


async def run_probe(cfg: ProbeConfig) -> int:
    from nats.aio.client import Client as NatsClient

    state = ProbeState(ts_window=deque(), lat_window=deque(), latencies=[])
    loop = asyncio.get_running_loop()
    start_mono = loop.time()

    client = NatsClient()
    options: dict[str, Any] = {
        "servers": [cfg.nats_url],
        "name": "nats-throughput-probe",
    }
    if cfg.user and cfg.password:
        options.update({"user": cfg.user, "password": cfg.password})
    await client.connect(**options)

    stop_event = asyncio.Event()

    async def _on_message(msg):  # type: ignore[no-untyped-def]
        _process_message(loop, cfg.window, msg, state)

    subscription = await client.subscribe("market.tick.>", cb=_on_message)

    async def reporter() -> None:
        while not stop_event.is_set():
            await asyncio.sleep(1.0)
            print(
                json.dumps(_window_report(loop, cfg.window, state), ensure_ascii=False)
            )

    reporter_task = asyncio.create_task(reporter())

    def _stop(_sig: int, _frame: Any | None = None) -> None:
        if not stop_event.is_set():
            stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(Exception):
            signal.signal(sig, _stop)

    await stop_event.wait()

    reporter_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await reporter_task
    with contextlib.suppress(Exception):
        await subscription.unsubscribe()
    await client.drain()
    await client.close()

    summary = _build_summary(loop.time() - start_mono, cfg.window, state)
    _maybe_write_summary(cfg, summary)
    print(json.dumps({"event": "probe_summary", **asdict(summary)}, ensure_ascii=False))
    return 0


def _process_message(
    loop: asyncio.AbstractEventLoop,
    window: float,
    msg: Any,
    state: ProbeState,
) -> None:
    now_mono = loop.time()
    state.ts_window.append(now_mono)
    cutoff = now_mono - window
    while state.ts_window and state.ts_window[0] < cutoff:
        state.ts_window.popleft()

    state.total += 1

    try:
        payload = json.loads(msg.data.decode() or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        state.json_errors += 1
        return

    timestamp_text = payload.get("timestamp") if isinstance(payload, dict) else None
    if not isinstance(timestamp_text, str):
        state.missing_ts += 1
        return

    dt = _parse_iso_dt(timestamp_text)
    if dt is None:
        state.missing_ts += 1
        return

    latency_ms = max(
        0.0, (datetime.now(UTC) - dt.astimezone(UTC)).total_seconds() * 1000.0
    )
    state.latencies.append(latency_ms)
    state.lat_window.append((now_mono, latency_ms))
    cutoff_lat = now_mono - window
    while state.lat_window and state.lat_window[0][0] < cutoff_lat:
        state.lat_window.popleft()


def _window_report(
    loop: asyncio.AbstractEventLoop, window: float, state: ProbeState
) -> dict[str, Any]:
    cutoff = loop.time() - window
    while state.ts_window and state.ts_window[0] < cutoff:
        state.ts_window.popleft()
    mps = len(state.ts_window) / window if window > 0 else 0.0

    cutoff_lat = loop.time() - window
    while state.lat_window and state.lat_window[0][0] < cutoff_lat:
        state.lat_window.popleft()
    window_lat = [entry[1] for entry in state.lat_window]
    stats = None
    if window_lat:
        stats = {
            "mean": round(sum(window_lat) / len(window_lat), 2),
            "p50": round(_percentiles(window_lat, [50])[0], 2),
            "p90": round(_percentiles(window_lat, [90])[0], 2),
            "p99": round(_percentiles(window_lat, [99])[0], 2),
        }
    return {
        "event": "probe_window",
        "timestamp": datetime.now(UTC).isoformat(),
        "mps": round(mps, 3),
        "window_latency": stats,
    }


def _build_summary(run_seconds: float, window: float, state: ProbeState) -> Summary:
    run_seconds = max(0.001, run_seconds)
    avg_mps = state.total / run_seconds
    last_mps = len(state.ts_window) / window if window > 0 else 0.0
    latencies = state.latencies
    lmin = min(latencies) if latencies else None
    lmax = max(latencies) if latencies else None
    mean = (sum(latencies) / len(latencies)) if latencies else None
    p50, p90, p99 = (
        _percentiles(latencies, [50, 90, 99]) if latencies else (None, None, None)
    )
    return Summary(
        run_seconds=round(run_seconds, 3),
        window_seconds=window,
        total_messages=state.total,
        avg_mps=round(avg_mps, 3),
        last_mps=round(last_mps, 3),
        latency_ms_min=None if lmin is None else round(lmin, 2),
        latency_ms_mean=None if mean is None else round(mean, 2),
        latency_ms_p50=None if p50 is None else round(p50, 2),
        latency_ms_p90=None if p90 is None else round(p90, 2),
        latency_ms_p99=None if p99 is None else round(p99, 2),
        latency_ms_max=None if lmax is None else round(lmax, 2),
        json_errors=state.json_errors,
        no_timestamp=state.missing_ts,
    )


def _maybe_write_summary(cfg: ProbeConfig, summary: Summary) -> None:
    if not cfg.out_path:
        return
    path = Path(os.fspath(cfg.out_path))
    path.parent.mkdir(parents=True, exist_ok=True)
    if cfg.out_format == "json":
        path.write_text(
            json.dumps(asdict(summary), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return
    if cfg.out_format == "csv":
        import csv

        data = asdict(summary)
        file_exists = path.exists()
        with path.open("a", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(data.keys()))
            if not file_exists:
                writer.writeheader()
            writer.writerow(data)
        return
    # Plain text fallback
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(asdict(summary), ensure_ascii=False) + "\n")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="NATS throughput & latency probe")
    parser.add_argument(
        "--nats-url", default=os.getenv("NATS_URL", "nats://localhost:4222")
    )
    parser.add_argument("--user", default=os.getenv("NATS_USER"))
    parser.add_argument("--password", default=os.getenv("NATS_PASSWORD"))
    parser.add_argument("--window", type=float, default=5.0)
    parser.add_argument("--format", choices=["text", "json", "csv"], default="text")
    parser.add_argument("--out", default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    cfg = ProbeConfig(
        nats_url=args.nats_url,
        user=args.user,
        password=args.password,
        window=max(0.1, float(args.window or 5.0)),
        out_format=str(args.format),
        out_path=args.out,
    )
    try:
        return asyncio.run(run_probe(cfg))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
