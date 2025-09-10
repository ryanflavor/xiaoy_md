"""Composition root to run live ingest behind env flags.

Environment:
  MD_RUN_INGEST=1           Enable ingest
  CTP_GATEWAY_CONNECT       module:attr of live connector
  CTP_SYMBOL                vt_symbol to subscribe
  MD_DURATION_SECONDS       Optional bounded runtime (0 = infinite)
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

from src.application.services import TickIngestService
from src.config import AppSettings
from src.infrastructure.ctp_adapter import CTPGatewayAdapter


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
    with contextlib.suppress(Exception):
        cast(Any, connector)._on_tick = adapter.on_tick  # noqa: SLF001

    service = TickIngestService(adapter, _NoopPublisher())
    await service.start()

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
        await service.stop()
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
