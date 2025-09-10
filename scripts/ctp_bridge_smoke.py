#!/usr/bin/env python3
"""Live CTP bridge smoke: validate sync→async bridging with real account.

Usage:
  # Ensure environment variables are set (can be in .env for local run):
  # CTP_BROKER_ID, CTP_USER_ID, CTP_PASSWORD, CTP_MD_ADDRESS, CTP_TD_ADDRESS,
  # CTP_APP_ID, CTP_AUTH_CODE, CTP_SYMBOL, CTP_GATEWAY_CONNECT
  # Optional: DURATION_SECONDS (default 30)

  uv run python scripts/ctp_bridge_smoke.py

This script loads a real vn.py CTP connector via CTP_GATEWAY_CONNECT and wires it
to the adapter's on_tick, then consumes ticks asynchronously for a bounded time.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import contextlib
from datetime import datetime
import importlib
import json
import os
from pathlib import Path
import signal
import sys
from typing import TYPE_CHECKING, Any, cast
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from types import FrameType

from src.config import AppSettings
from src.infrastructure.ctp_adapter import CTPGatewayAdapter


def _load_env_file() -> None:
    path = Path.cwd() / ".env"
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


def _load_connector_from_env() -> (
    Callable[[dict[str, object], Callable[[], bool]], None]
):
    target = os.environ.get("CTP_GATEWAY_CONNECT")
    if not target:
        raise ValueError
    if ":" in target:
        module_path, attr = target.split(":", 1)
    else:
        module_path, attr = target.rsplit(".", 1)
    module = importlib.import_module(module_path)
    fn = getattr(module, attr)
    if not callable(fn):
        raise TypeError
    return cast(Callable[[dict[str, object], Callable[[], bool]], None], fn)


async def main() -> int:
    _load_env_file()

    required = [
        "CTP_BROKER_ID",
        "CTP_USER_ID",
        "CTP_PASSWORD",
        "CTP_MD_ADDRESS",
        "CTP_TD_ADDRESS",
        "CTP_APP_ID",
        "CTP_AUTH_CODE",
        "CTP_SYMBOL",
        "CTP_GATEWAY_CONNECT",
    ]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        print(
            json.dumps(
                {
                    "level": "error",
                    "event": "ctp_bridge_smoke_missing_env",
                    "missing": missing,
                }
            )
        )
        return 2

    duration = int(os.environ.get("DURATION_SECONDS", "30"))
    symbol = os.environ["CTP_SYMBOL"]

    settings = AppSettings()
    gateway_connect = _load_connector_from_env()

    adapter = CTPGatewayAdapter(settings, gateway_connect=gateway_connect)
    # Attach adapter-bound on_tick so the connector can forward TickData
    with contextlib.suppress(Exception):
        cast(Any, gateway_connect)._on_tick = adapter.on_tick  # noqa: SLF001

    # Best-effort contract gate: allow base symbol until real contracts loaded.
    base_symbol = symbol.split(".")[0]
    adapter.symbol_contract_map[base_symbol] = object()

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _handle_stop(_sig: int, _frame: FrameType | None = None) -> None:
        if not stop_event.is_set():
            stop_event.set()

    with contextlib.suppress(Exception):
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, _handle_stop)

    # Diagnostic start line
    china_tz = ZoneInfo("Asia/Shanghai")
    print(
        json.dumps(
            {
                "event": "ctp_bridge_start",
                "connector": os.environ.get("CTP_GATEWAY_CONNECT"),
                "symbol": symbol,
                "duration_sec": duration,
            }
        )
    )

    await adapter.connect()

    end = loop.time() + float(duration)
    count = 0

    async def consume() -> None:
        nonlocal count
        async for tick in adapter.receive_ticks():
            count += 1
            print(
                json.dumps(
                    {
                        "ts": datetime.now(china_tz).isoformat(),
                        "event": "ctp_bridge_tick",
                        "symbol": getattr(tick, "symbol", None),
                        "price": str(getattr(tick, "price", None)),
                    }
                )
            )
            if loop.time() >= end or stop_event.is_set():
                break

    try:
        await asyncio.wait_for(consume(), timeout=duration + 5.0)
    except TimeoutError:
        pass
    finally:
        await adapter.disconnect()

    print(
        json.dumps(
            {
                "event": "ctp_bridge_smoke_summary",
                "received": count,
                "duration_sec": duration,
            }
        )
    )
    return 0


if __name__ == "__main__":
    try:
        code = asyncio.run(main())
    except KeyboardInterrupt:
        code = 130
    sys.exit(code)
