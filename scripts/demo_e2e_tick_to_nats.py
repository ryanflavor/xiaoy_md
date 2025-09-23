# ruff: noqa: PLR0915
"""Demo: Emit a vnpy-like tick and capture it via NATS.

This script composes the following in-process:
- CTPGatewayAdapter (with an injected `gateway_connect` that emits one tick)
- MarketDataService
- NATSPublisher (real nats-py client)

It also starts an ephemeral NATS container (no auth) and subscribes with a
real nats-py subscriber to verify the subject and payload end-to-end.

Usage examples:
  uv run python scripts/demo_e2e_tick_to_nats.py
  uv run python scripts/demo_e2e_tick_to_nats.py --base-symbol IF2503 --exchange CFFEX

Requirements:
- Docker daemon must be running and accessible
- Project dependencies installed (e.g., `uv sync`)
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import datetime
import json
import socket
import subprocess
import sys
import time
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

import nats

from src.application.services import MarketDataService, ServiceDependencies
from src.config import AppSettings
from src.infrastructure.ctp_adapter import CTPGatewayAdapter
from src.infrastructure.nats_publisher import NATSPublisher

if TYPE_CHECKING:
    from collections.abc import Callable


def _choose_port(preferred: int) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", preferred))
        except OSError:
            s.bind(("127.0.0.1", 0))
            return int(s.getsockname()[1])
        else:
            return preferred


def _start_nats_container(name: str, wait_seconds: float = 3.0) -> dict[str, int | str]:
    # Remove any existing container with same name
    subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)

    client_port = _choose_port(4222)
    monitor_port = _choose_port(8222)

    res = subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            name,
            "-p",
            f"{client_port}:4222",
            "-p",
            f"{monitor_port}:8222",
            "nats:latest",
            "-js",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if res.returncode != 0:
        raise RuntimeError

    # Wait for readiness (logs indicate server ready)
    ready = False
    start = time.time()
    while time.time() - start < wait_seconds:
        logs = subprocess.run(
            ["docker", "logs", name],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        ).stdout
        if "Server is ready" in logs or "Listening for client connections" in logs:
            ready = True
            break
        time.sleep(0.1)

    if not ready:
        logs = subprocess.run(
            ["docker", "logs", name],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        ).stdout
        subprocess.run(["docker", "rm", "-f", name], check=False)
        raise RuntimeError

    return {"client_port": client_port, "monitor_port": monitor_port, "name": name}


@dataclass
class _StubTick:
    symbol: str
    last_price: float
    volume: int
    datetime: datetime
    bid_price_1: float
    ask_price_1: float


async def _run_demo(
    base_symbol: str, exchange: str, ts: str | None, keep_container: bool
) -> int:
    container_name = "demo-nats-e2e"
    try:
        nats_info = _start_nats_container(container_name)
    except Exception as e:  # noqa: BLE001
        print(f"Failed to start NATS: {e}")
        return 2

    # Prepare vnpy-like tick
    china_tz = ZoneInfo("Asia/Shanghai")
    if ts:
        # Accept ISO string, with or without tz; default to +08:00
        try:
            # If no tzinfo suffix, assume +08:00
            if ts.endswith("Z") or "+" in ts[10:]:
                tick_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                tick_dt = tick_dt.astimezone(china_tz)
            else:
                y, mo, d = map(int, ts[0:10].split("-"))
                hh, mm, ss = map(int, ts[11:19].split(":"))
                tick_dt = datetime(y, mo, d, hh, mm, ss, tzinfo=china_tz)
        except Exception:  # noqa: BLE001
            print("Invalid --ts format, expected ISO-8601. Falling back to default.")
            tick_dt = datetime(2025, 1, 1, 9, 30, 0, tzinfo=china_tz)
    else:
        tick_dt = datetime(2025, 1, 1, 9, 30, 0, tzinfo=china_tz)

    vt_symbol = f"{base_symbol}.{exchange}"
    expected_subject = f"market.tick.{exchange}.{base_symbol}"
    stub_tick = _StubTick(
        symbol=vt_symbol,
        last_price=1234.5,
        volume=10,
        datetime=tick_dt,
        bid_price_1=1234.4,
        ask_price_1=1234.6,
    )

    nats_url = f"nats://localhost:{nats_info['client_port']}"
    settings = AppSettings(
        nats_url=nats_url, nats_client_id="e2e-demo", environment="test"
    )

    publisher = NATSPublisher(settings)

    adapter_ref: dict[str, CTPGatewayAdapter] = {}

    def gateway_connect(
        _setting: dict[str, Any], _should_shutdown: Callable[[], bool]
    ) -> None:
        # Emit exactly one tick from the worker thread
        adapter_ref["adapter"].on_tick(stub_tick)

    adapter = CTPGatewayAdapter(settings, gateway_connect=gateway_connect)
    adapter_ref["adapter"] = adapter
    adapter.symbol_contract_map[base_symbol] = object()
    adapter.symbol_contract_map[vt_symbol] = object()

    service = MarketDataService(
        ports=ServiceDependencies(market_data=adapter, publisher=publisher)
    )

    nc = await nats.connect(nats_url)
    payload_box: dict[str, Any] = {}
    evt = asyncio.Event()

    async def cb(msg):  # type: ignore[no-untyped-def]
        payload_box["subject"] = msg.subject
        payload_box["payload"] = json.loads(msg.data.decode())
        evt.set()

    sub = await nc.subscribe(expected_subject, cb=cb)

    # Start components
    await publisher.connect()
    await adapter.connect()
    proc_task = asyncio.create_task(service.process_market_data())

    try:
        await asyncio.wait_for(evt.wait(), timeout=5.0)
    except TimeoutError:
        logs = subprocess.run(
            ["docker", "logs", str(nats_info["name"])],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        ).stdout
        print("Timed out waiting for message. Recent NATS logs:\n" + logs[-2000:])
        rc = 1
    else:
        # Print evidence
        print("NATS subject:", payload_box.get("subject"))
        print("Payload:", json.dumps(payload_box.get("payload"), ensure_ascii=False))
        rc = 0
    finally:
        # Cleanup
        proc_task.cancel()
        import contextlib as _ctx

        with _ctx.suppress(asyncio.CancelledError):
            await proc_task
        import contextlib as _ctx

        with _ctx.suppress(Exception):
            await sub.unsubscribe()
        await adapter.disconnect()
        await publisher.disconnect()
        await nc.close()
        if not keep_container:
            subprocess.run(
                ["docker", "rm", "-f", str(nats_info["name"])],
                capture_output=True,
                check=False,
            )
        else:
            print(
                f"Kept container: {nats_info['name']} (client port {nats_info['client_port']})"
            )

    return rc


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="E2E demo: emit vnpy-like tick and capture via NATS"
    )
    p.add_argument("--base-symbol", default="IF2312", help="Base symbol (e.g., IF2312)")
    p.add_argument("--exchange", default="CFFEX", help="Exchange (e.g., CFFEX)")
    p.add_argument(
        "--ts",
        default=None,
        help="ISO-8601 timestamp (assumes +08:00 if missing tz). Default 2025-01-01T09:30:00+08:00",
    )
    p.add_argument(
        "--keep-container",
        action="store_true",
        help="Do not remove the NATS container after the demo ends",
    )
    return p.parse_args(argv)


def main(argv: list[str]) -> int:
    args = _parse_args(argv)
    try:
        return asyncio.run(
            _run_demo(
                base_symbol=args.base_symbol,
                exchange=args.exchange,
                ts=args.ts,
                keep_container=bool(args.keep_container),
            )
        )
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
