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
import os
import signal
from typing import TYPE_CHECKING, Any, cast

from src.application.services import MarketDataService
from src.config import AppSettings
from src.infrastructure.ctp_adapter import CTPGatewayAdapter
from src.infrastructure.nats_publisher import NATSPublisher


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


class _NoopPublisher:
    async def publish_tick(self, _tick: object) -> None:
        return None


async def _run() -> int:
    settings = AppSettings()
    connector = _load_connector_from_env()
    adapter = CTPGatewayAdapter(settings, gateway_connect=connector)
    logger = logging.getLogger(__name__)
    # Prefer public API for binding on_tick, fallback to private attribute
    with contextlib.suppress(Exception):
        target = os.environ.get("CTP_GATEWAY_CONNECT")
        if target:
            module_path = (
                target.split(":", 1)[0] if ":" in target else target.rsplit(".", 1)[0]
            )
            mod = importlib.import_module(module_path)
            setter = getattr(mod, "set_on_tick", None)
            if callable(setter):
                setter(adapter.on_tick)
            else:
                cast(Any, connector)._on_tick = adapter.on_tick  # noqa: SLF001

    # Seed symbol contract map for initial routing readiness if CTP_SYMBOL provided.
    vt_symbol = os.environ.get("CTP_SYMBOL")
    if vt_symbol:
        # Accept both vt_symbol and base symbol to maximize compatibility
        adapter.symbol_contract_map[vt_symbol] = object()
        if "." in vt_symbol:
            base, _ex = vt_symbol.rsplit(".", 1)
            adapter.symbol_contract_map[base] = object()

    # Compose service graph: adapter + NATSPublisher via MarketDataService
    publisher = NATSPublisher(settings)
    service = MarketDataService(market_data_port=adapter, publisher_port=publisher)

    # Connect components
    await adapter.connect()
    await publisher.connect()

    # Start processing loop in background
    proc_task = asyncio.create_task(service.process_market_data())

    stop = asyncio.Event()

    def _handle(_sig: int, _frame: FrameType | None = None) -> None:
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
        await adapter.disconnect()
        await publisher.disconnect()
        # Log publish stats for observability
        try:
            stats = publisher.get_connection_stats()
            logger.info(
                "live_ingest_shutdown",
                extra={
                    "published": stats.get("successful_publishes"),
                    "failed": stats.get("failed_publishes"),
                },
            )
        except Exception:
            logger.debug("publisher_stats_unavailable")
    return 0


def main() -> int:
    if os.environ.get("MD_RUN_INGEST") != "1":
        logging.basicConfig(level=logging.INFO, format="%(message)s")
        logging.getLogger(__name__).info(
            "ingest_disabled_set_MD_RUN_INGEST=1_to_enable"
        )
        return 0
    try:
        return asyncio.run(_run())
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
if TYPE_CHECKING:
    from types import FrameType
