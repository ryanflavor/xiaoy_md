#!/usr/bin/env python3
"""Live CTP Observability Integration Check (Story 2.4.4).

Composes CTPGatewayAdapter + MarketDataService + NATSPublisher using your
.env live settings and connector, subscribes to the expected market subject,
runs for a bounded duration, and captures:
  - mps_report logs (windowed MPS and cumulative counters)
  - received message count via real NATS subscriber
  - publisher connection stats

Outputs results to a writable directory (e.g., .logs/).

Usage:
  uv run python scripts/live_ctp_observability_check.py --duration 15
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import importlib
import json
import logging
import os
from pathlib import Path
from typing import Any, cast

import nats

from src.application.services import (
    MarketDataService,
    MetricsConfig,
    ServiceDependencies,
)
from src.config import AppSettings
from src.infrastructure.ctp_adapter import CTPGatewayAdapter
from src.infrastructure.nats_publisher import NATSPublisher

MIN_RUN_SECONDS = 2
MPS_WINDOW_SECONDS = 2.0
MPS_MIN_SAMPLES = 2


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    with contextlib.suppress(Exception), path.open(encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k and v and k not in os.environ:
                os.environ[k] = v


def _choose_output_dir() -> Path:
    # Prefer a stable absolute path to avoid env quirks
    base = Path.cwd() / "observability_results"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _resolve_connector() -> Any:
    target = os.environ.get("CTP_GATEWAY_CONNECT")
    if not target:
        msg = "CTP_GATEWAY_CONNECT env var must be set"
        raise RuntimeError(msg)
    if ":" in target:
        module_path, attr = target.split(":", 1)
    else:
        module_path, attr = target.rsplit(".", 1)
    mod = importlib.import_module(module_path)
    fn = getattr(mod, attr)
    if not callable(fn):
        raise TypeError("connector_not_callable")
    return fn


def _bind_on_tick(adapter: CTPGatewayAdapter, connector: object) -> None:
    import importlib as _importlib

    with contextlib.suppress(Exception):
        target = os.environ.get("CTP_GATEWAY_CONNECT")
        if not target:
            return
        module_path = (
            target.split(":", 1)[0] if ":" in target else target.rsplit(".", 1)[0]
        )
        mod = _importlib.import_module(module_path)
        setter = getattr(mod, "set_on_tick", None)
        if callable(setter):
            setter(adapter.on_tick)
        else:
            cast(Any, connector)._on_tick = adapter.on_tick  # noqa: SLF001


class _MPSCaptureHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.records: list[dict[str, Any]] = []

    def emit(
        self, record: logging.LogRecord
    ) -> None:  # pragma: no cover - integration only
        try:
            if getattr(record, "event", "") == "mps_report":
                self.records.append(
                    {
                        "window_seconds": getattr(record, "window_seconds", None),
                        "mps_window": getattr(record, "mps_window", None),
                        "published_total": getattr(record, "published_total", None),
                        "dropped_total": getattr(record, "dropped_total", None),
                        "failed_total": getattr(record, "failed_total", None),
                        "nats_connected": getattr(record, "nats_connected", None),
                    }
                )
        except (AttributeError, TypeError):
            return


async def _amain(duration: int) -> int:  # noqa: PLR0915 - sequential orchestration
    _load_env_file(Path.cwd() / ".env")
    out_dir = _choose_output_dir()

    settings = AppSettings()
    connector = _resolve_connector()
    adapter = CTPGatewayAdapter(settings, gateway_connect=connector)
    publisher = NATSPublisher(settings)

    # Route adapter.on_tick into live connector
    _bind_on_tick(adapter, connector)

    # Subject and subscriber
    vt_symbol = os.environ.get("CTP_SYMBOL") or "IF2312.CFFEX"
    if "." in vt_symbol:
        base, ex = vt_symbol.rsplit(".", 1)
    else:
        base, ex = vt_symbol, "UNKNOWN"
    subject = f"market.tick.{ex}.{base}"

    # Seed contract map so adapter accepts ticks before live contracts load
    adapter.symbol_contract_map[base] = object()
    adapter.symbol_contract_map[vt_symbol] = object()

    # Attach capture handler for mps_report
    capture = _MPSCaptureHandler()
    logger = logging.getLogger("src.application.services")
    logger.addHandler(capture)
    logger.setLevel(logging.INFO)

    # Compose service with shorter reporter window (faster sampling for test)
    service = MarketDataService(
        ports=ServiceDependencies(
            market_data=adapter,
            publisher=publisher,
        ),
        metrics=MetricsConfig(
            window_seconds=MPS_WINDOW_SECONDS,
            report_interval_seconds=MPS_WINDOW_SECONDS,
        ),
    )

    # NATS subscriber with possible auth
    nats_kwargs: dict[str, Any] = {"servers": [settings.nats_url]}
    if settings.nats_user and settings.nats_password:
        nats_kwargs.update(
            {"user": settings.nats_user, "password": settings.nats_password}
        )
    nc = await nats.connect(**nats_kwargs)
    recv_count = 0
    recv_ts: list[float] = []
    loop = asyncio.get_running_loop()

    async def _cb(_msg: Any) -> None:
        nonlocal recv_count
        recv_count += 1
        recv_ts.append(loop.time())

    sub = await nc.subscribe(subject, cb=_cb)

    # Start components
    await adapter.connect()
    await publisher.connect()
    proc_task = asyncio.create_task(service.process_market_data())

    # Run for bounded duration
    try:
        await asyncio.sleep(float(max(MIN_RUN_SECONDS, duration)))
    finally:
        proc_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await proc_task
        await adapter.disconnect()
        await publisher.disconnect()
        with contextlib.suppress(Exception):
            await sub.unsubscribe()
        with contextlib.suppress(Exception):
            await nc.close()
        with contextlib.suppress(Exception):
            logger.removeHandler(capture)

    # Publisher stats and snapshot
    stats = publisher.get_connection_stats()
    snapshot = service.get_metrics_snapshot()

    # Approx subscriber-derived MPS over the last window
    approx_mps = None
    if len(recv_ts) >= MPS_MIN_SAMPLES:
        win = MPS_WINDOW_SECONDS
        cutoff = loop.time() - win
        recent = [t for t in recv_ts if t >= cutoff]
        approx_mps = round(len(recent) / win, 3)

    result = {
        "ok": True,
        "nats_url": settings.nats_url,
        "subject": subject,
        "received_total": recv_count,
        "approx_mps_last2s": approx_mps,
        "mps_reports": capture.records,
        "publisher_stats": stats,
        "service_snapshot": snapshot,
    }

    ts = f"{int(asyncio.get_running_loop().time()*1000)}"
    json_path = out_dir / f"live-ctp-observability-{ts}.json"
    log_path = out_dir / f"live-ctp-observability-{ts}.log"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    lines = [
        f"Live CTP Observability — subject: {subject}",
        f"received_total: {recv_count}",
        f"approx_mps_last2s: {approx_mps}",
        f"last_mps_report: {json.dumps(capture.records[-1] if capture.records else {}, ensure_ascii=False)}",
    ]
    log_path.write_text("\n".join(lines))
    print(
        json.dumps(
            {
                "ok": True,
                "json": str(json_path),
                "log": str(log_path),
                "last_mps_report": (capture.records[-1] if capture.records else {}),
                "snapshot": snapshot,
            },
            ensure_ascii=False,
        )
    )
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--duration", type=int, default=12, help="Run duration in seconds")
    args = ap.parse_args()
    try:
        return asyncio.run(_amain(args.duration))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
