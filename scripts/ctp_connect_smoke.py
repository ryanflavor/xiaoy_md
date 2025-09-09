#!/usr/bin/env python3
"""Local-only CTP connectivity smoke test for Story 2.1a.

Purpose
- Verify real CTP login and supervised retry behavior using CTPGatewayAdapter
- Run for a short, bounded time (default 120s) and exit cleanly
- Produce structured JSON logs; never print secrets

Key failure scenarios handled:
- 交易服务器登录失败 (login failed) - triggers retry with backoff
- 交易服务器授权验证失败 (auth failed) - triggers retry
- 交易/行情服务器连接断开 (connection lost) - triggers reconnection
- Any ERROR level messages - captured as failures

Usage
  1) Ensure dependencies are installed locally (not in CI):
       uv add vnpy vnpy_ctp
  2) Provide credentials via environment variables (case-insensitive):
       CTP_BROKER_ID, CTP_USER_ID, CTP_PASSWORD,
       CTP_MD_ADDRESS, CTP_TD_ADDRESS, CTP_APP_ID, CTP_AUTH_CODE
  3) Run the smoke test (during trading hours if needed):
       uv run python scripts/ctp_connect_smoke.py --duration 120

Notes
-----
- This script is intended for local developer execution only.
- Do not commit secrets; all configuration is read from .env or shell env.
- Subscriptions / event bridging are out of scope for this smoke.

"""

from __future__ import annotations

import argparse
import asyncio as aio
import json
import logging
import sys
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable


from src.config import settings
from src.infrastructure.ctp_adapter import CTPGatewayAdapter

# Constants for log levels and intervals
ERROR_LEVEL = 40
WARNING_LEVEL = 30
HEARTBEAT_INTERVAL = 3.0


class JsonFormatter(logging.Formatter):
    """Minimal JSON log formatter; includes adapter retry extras if present."""

    def format(self, record: logging.LogRecord) -> str:
        data: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "time": time.strftime(
                "%Y-%m-%dT%H:%M:%S%z", time.localtime(record.created)
            ),
        }
        # Include adapter supervision extras when present
        for key in ("attempt", "reason", "next_backoff"):
            if hasattr(record, key):
                data[key] = getattr(record, key)
        return json.dumps(data, ensure_ascii=False)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))


def _create_event_handlers(
    connection_status: dict[str, Any], log: logging.Logger
) -> tuple[Any, Any]:
    """Create event handlers for CTP events."""
    try:
        from vnpy.event import Event  # type: ignore[import-untyped]  # noqa: TC002
        from vnpy.trader.object import LogData  # type: ignore  # noqa: F401, PGH003
    except ImportError:
        return None, None

    def on_log(event: Event) -> None:
        log_data = event.data  # type: LogData
        msg = log_data.msg
        level = log_data.level

        # Log with appropriate level
        if level == ERROR_LEVEL:
            log.error(f"ctp_event: {msg}")
            connection_status["error"] = msg
        elif "登录失败" in msg or "认证失败" in msg or "授权验证失败" in msg:
            # Some failures come as INFO level
            connection_status["error"] = msg
        elif "连接断开" in msg:
            # Connection lost - need to reconnect
            connection_status["connected"] = False
            connection_status["error"] = msg
            log.warning(f"ctp_smoke_disconnected: {msg}")
        elif level == WARNING_LEVEL:
            log.warning(f"ctp_event: {msg}")
        else:
            log.info(f"ctp_event: {msg}")

        # Check for successful connection indicators
        if "交易服务器登录成功" in msg or "行情服务器登录成功" in msg:
            connection_status["connected"] = True
            log.info("ctp_smoke_connected")

    def on_contract(event: Event) -> None:  # noqa: ARG001
        # Receipt of contract data indicates successful connection
        if not connection_status["connected"]:
            connection_status["connected"] = True
            log.info("ctp_smoke_connected_contracts_received")

    return on_log, on_contract


def _wait_for_connection(
    connection_status: dict[str, Any], log: logging.Logger
) -> None:
    """Wait for CTP connection with timeout."""
    wait_time = 0.0
    max_wait = 10  # 10 seconds to establish connection
    while (
        wait_time < max_wait
        and not connection_status["connected"]
        and not connection_status["error"]
    ):
        time.sleep(0.5)
        wait_time += 0.5

    if connection_status["error"]:
        error_msg = f"CTP connection failed: {connection_status['error']}"
        raise RuntimeError(error_msg)
    if not connection_status["connected"]:
        log.warning("ctp_smoke_connection_timeout")


def real_ctp_gateway_connect(
    setting: dict[str, Any], should_shutdown: Callable[[], bool]
) -> None:
    """Run a real vn.py CTP gateway session.

    Notes:
    - Requires local installation of vnpy + vnpy_ctp
    - Avoids logging secrets; relies on adapter to log supervision details

    """
    try:
        from vnpy.event import EventEngine
        from vnpy.trader.engine import MainEngine  # type: ignore[import-untyped]
        from vnpy_ctp import CtpGateway  # type: ignore[import-untyped]
    except ImportError as exc:
        msg = "vnpy/vnpy_ctp not installed. Install locally via 'uv add vnpy vnpy_ctp'"
        raise RuntimeError(msg) from exc

    log = logging.getLogger(__name__)
    event_engine = EventEngine()
    main_engine = MainEngine(event_engine)

    # Track connection status
    connection_status = {"connected": False, "error": None}

    # Create and register event handlers
    on_log, on_contract = _create_event_handlers(connection_status, log)
    if on_log and on_contract:
        event_engine.register("eLog", on_log)
        event_engine.register("eContract", on_contract)

    # Register CTP gateway
    main_engine.add_gateway(CtpGateway)

    # Attempt connect; support both common call signatures
    try:
        # Some versions expect (setting, gateway_name)
        main_engine.connect(setting, "CTP")
    except TypeError:
        # Others expect (gateway_name, setting)
        main_engine.connect("CTP", setting)

    log.info("ctp_smoke_connect_initiated")

    # Wait for connection or error
    _wait_for_connection(connection_status, log)

    # Idle loop until asked to shutdown
    try:
        last = 0.0
        while not should_shutdown():
            now = time.time()
            if now - last >= HEARTBEAT_INTERVAL:
                log.info(
                    "ctp_smoke_heartbeat",
                    extra={"connected": connection_status["connected"]},
                )
                last = now
            time.sleep(0.1)
    finally:
        import contextlib

        with contextlib.suppress(Exception):
            main_engine.close()


async def run(duration: float) -> int:
    log = logging.getLogger(__name__)

    # Basic presence checks for required fields; adapter will normalize addresses
    missing = []
    if not settings.ctp_broker_id:
        missing.append("CTP_BROKER_ID")
    if not settings.ctp_user_id:
        missing.append("CTP_USER_ID")
    if not settings.ctp_password:
        missing.append("CTP_PASSWORD")
    if not settings.ctp_md_address:
        missing.append("CTP_MD_ADDRESS")
    if not settings.ctp_td_address:
        missing.append("CTP_TD_ADDRESS")
    if not settings.ctp_app_id:
        missing.append("CTP_APP_ID")
    if not settings.ctp_auth_code:
        missing.append("CTP_AUTH_CODE")

    if missing:
        log.error(
            "ctp_smoke_missing_env",
            extra={"missing": ",".join(missing)},
        )
        return 2

    adapter = CTPGatewayAdapter(settings, gateway_connect=real_ctp_gateway_connect)

    log.info("ctp_smoke_start", extra={"duration_sec": duration})
    try:
        await adapter.connect()
        await aio.sleep(duration)
        await adapter.disconnect()
    except KeyboardInterrupt:
        log.info("ctp_smoke_interrupt")
        await adapter.disconnect()
    except Exception as exc:
        # Supervisor inside adapter will already emit structured retry logs
        log.exception("ctp_smoke_exception", extra={"reason": str(exc)})
        return 1

    log.info("ctp_smoke_done")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CTP connectivity smoke test")
    parser.add_argument(
        "--duration",
        type=float,
        default=120.0,
        help="Run duration in seconds (default: 120)",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default=settings.log_level if settings.log_level else "INFO",
        help="Logging level (default: from settings or INFO)",
    )
    args = parser.parse_args(argv)

    configure_logging(args.log_level)
    return aio.run(run(args.duration))


if __name__ == "__main__":
    raise SystemExit(main())
