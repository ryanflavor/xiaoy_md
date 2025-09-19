"""Composition root to run live ingest behind env flags.

Environment:
  MD_RUN_INGEST=1           Enable ingest
  CTP_GATEWAY_CONNECT       module:attr of live connector
  CTP_SYMBOL                vt_symbol to subscribe (used for initial routing readiness)
  MD_DURATION_SECONDS       Optional bounded runtime (0 = infinite)
  NATS_URL/NATS_USER/NATS_PASSWORD respected via AppSettings
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import contextlib
import importlib
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import signal
from typing import Any, cast

from src.application.services import MarketDataService, RateLimitConfig
from src.config import AppSettings
from src.infrastructure.ctp_adapter import CTPGatewayAdapter
from src.infrastructure.nats_publisher import NATSPublisher
from src.infrastructure.rpc_nats import NATSRPCServer

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%dT%H:%M:%S%z"


class ConnectorConfigError(ValueError):
    """Raised when the CTP connector environment variable is missing."""

    def __init__(self) -> None:
        """Initialize error with human-friendly guidance."""
        super().__init__("Missing CTP_GATEWAY_CONNECT. Set module:attr path.")


class ConnectorCallableError(TypeError):
    """Raised when the resolved connector target is not callable."""

    def __init__(self) -> None:
        """Initialize error describing expected callable reference."""
        super().__init__("CTP_GATEWAY_CONNECT must reference a callable")


def _configure_logging() -> None:
    """Configure stdout + rotating file logging for live ingest."""
    formatter = logging.Formatter(fmt=LOG_FORMAT, datefmt=DATE_FORMAT)
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, datefmt=DATE_FORMAT)
    root = logging.getLogger()

    # Avoid attaching duplicate file handlers when main() re-enters (tests).
    for handler in root.handlers:
        if getattr(handler, "live_ingest_file", False):
            return

    logs_dir = Path(os.environ.get("LIVE_INGEST_LOG_DIR", "/app/logs"))
    try:
        logs_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            logs_dir / "live_ingest.log",
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.live_ingest_file = True  # type: ignore[attr-defined]
        root.addHandler(file_handler)
    except OSError as exc:
        logging.getLogger(__name__).warning(
            "log_file_setup_failed", extra={"error": str(exc), "path": str(logs_dir)}
        )


def _load_connector_from_env() -> (
    Callable[[dict[str, object], Callable[[], bool]], None]
):
    target = os.environ.get("CTP_GATEWAY_CONNECT")
    if not target:
        raise ConnectorConfigError
    if ":" in target:
        module_path, attr = target.split(":", 1)
    else:
        module_path, attr = target.rsplit(".", 1)
    module = importlib.import_module(module_path)
    fn = getattr(module, attr)
    if not callable(fn):
        raise ConnectorCallableError
    return cast(Callable[[dict[str, object], Callable[[], bool]], None], fn)


class _NoopPublisher:
    async def publish_tick(self, _tick: object) -> None:
        return None


def _bind_on_tick(adapter: CTPGatewayAdapter, connector: object) -> None:
    """Bind adapter.on_tick to live connector if setter is available.

    Falls back to setting a known attribute on the connector function when needed.
    """
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


def _seed_contract_map(adapter: CTPGatewayAdapter, vt_symbol: str | None) -> None:
    """Populate adapter contract map with vt/base symbol for initial readiness."""
    if not vt_symbol:
        return
    adapter.symbol_contract_map[vt_symbol] = object()
    if "." in vt_symbol:
        base, _ex = vt_symbol.rsplit(".", 1)
        adapter.symbol_contract_map[base] = object()


async def _run() -> int:
    settings = AppSettings()
    # Auto-switch NATS URL when requested: inside Docker use hostname 'nats',
    # on host use localhost. Enable by setting LIVE_NATS_AUTOMODE=1.
    if os.environ.get("LIVE_NATS_AUTOMODE") == "1":
        in_docker = Path("/.dockerenv").exists()
        auto_url = "nats://nats:4222" if in_docker else "nats://127.0.0.1:4222"
        os.environ["NATS_URL"] = auto_url
        settings = AppSettings()  # reload to pick updated env
    connector = _load_connector_from_env()
    adapter = CTPGatewayAdapter(settings, gateway_connect=connector)
    logger = logging.getLogger(__name__)
    # Prefer public API for binding on_tick, fallback to private attribute
    _bind_on_tick(adapter, connector)

    vt_symbol = os.environ.get("CTP_SYMBOL")
    _seed_contract_map(adapter, vt_symbol)

    # Compose service graph: adapter + NATSPublisher via MarketDataService
    publisher = NATSPublisher(settings)
    service = MarketDataService(
        market_data_port=adapter,
        publisher_port=publisher,
        rate_limits=RateLimitConfig(
            window_seconds=settings.subscribe_rate_limit_window_seconds,
            max_requests=settings.subscribe_rate_limit_max_requests,
        ),
    )

    # Connect components
    await adapter.connect()
    await publisher.connect()

    # Start processing loop in background
    proc_task = asyncio.create_task(service.process_market_data())

    # Expose RPC control plane in live process so md.subscribe.bulk affects this adapter
    rpc_server = NATSRPCServer(settings, service, adapter)
    await rpc_server.start()

    stop = asyncio.Event()

    def _handle(_sig: int, _frame: object | None = None) -> None:
        if not stop.is_set():
            stop.set()

    with contextlib.suppress(Exception):
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, _handle)

    duration = int(os.environ.get("MD_DURATION_SECONDS", "0") or "0")
    try:
        if duration > 0:
            await asyncio.wait_for(stop.wait(), timeout=duration)
        else:
            await stop.wait()
    except TimeoutError:
        pass
    finally:
        # Graceful shutdown: stop processing, disconnect components
        proc_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await proc_task
        with contextlib.suppress(Exception):
            await rpc_server.stop()
        await adapter.disconnect()
        await publisher.disconnect()
        # Log publish stats for observability
        with contextlib.suppress(Exception):
            stats = publisher.get_connection_stats()
            logger.info(
                "live_ingest_shutdown",
                extra={
                    "published": stats.get("successful_publishes"),
                    "failed": stats.get("failed_publishes"),
                },
            )
    return 0


def _log_optional_env_warnings() -> None:
    """Emit readability warnings for optional-but-recommended envs."""
    logger = logging.getLogger(__name__)
    if not os.environ.get("CTP_SYMBOL"):
        logger.warning(
            "live_ingest_optional_env_missing",
            extra={
                "var": "CTP_SYMBOL",
                "hint": "Set a vt_symbol (e.g. rb9999.SHFE) to seed routing readiness",
            },
        )


def main() -> int:
    if os.environ.get("MD_RUN_INGEST") != "1":
        logging.basicConfig(level=logging.INFO, format="%(message)s")
        logging.getLogger(__name__).info(
            "ingest_disabled_set_MD_RUN_INGEST=1_to_enable"
        )
        return 0
    # Ensure readable logging for startup diagnostics
    _configure_logging()
    _log_optional_env_warnings()
    try:
        return asyncio.run(_run())
    except KeyboardInterrupt:
        return 130
    except (ValueError, ModuleNotFoundError, AttributeError, TypeError) as exc:
        logging.getLogger(__name__).exception(
            "live_ingest_startup_error",
            extra={
                "error": str(exc),
                "required_env": ["CTP_GATEWAY_CONNECT"],
                "configure_in": [
                    ".env",
                    "docker-compose live profile",
                    "shell environment",
                ],
                "example": {
                    "CTP_GATEWAY_CONNECT": (
                        "src.infrastructure.ctp_live_connector:live_gateway_connect"
                    )
                },
            },
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
