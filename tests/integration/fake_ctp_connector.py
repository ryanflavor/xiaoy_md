"""Fake CTP connector module for live ingest entrypoint tests.

Provides `set_on_tick(cb)` and `gateway_connect(setting, should_shutdown)` so that
`src.main` can import and bind the callback via CTP_GATEWAY_CONNECT. It emits a
single vnpy-like TickData to exercise the adapter → service → NATS path.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import os
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from collections.abc import Callable


def set_on_tick(callback: Any) -> None:  # production API expected by src.main
    # Store on function attribute to avoid module-level globals
    gateway_connect.on_tick = callback  # type: ignore[attr-defined]


@dataclass
class _StubTick:
    symbol: str
    last_price: float
    volume: int
    datetime: datetime
    bid_price_1: float
    ask_price_1: float


def gateway_connect(
    setting: dict[str, object], should_shutdown: Callable[[], bool]
) -> None:
    """Emit one tick and return to let the session end cleanly."""
    cb = getattr(gateway_connect, "on_tick", None)
    if cb is None:
        return

    # Determine symbol from env (align with test expectations)
    vt_symbol = os.environ.get("CTP_SYMBOL") or "IF2312.CFFEX"

    # Use China timezone for consistency with project policy
    china_tz = ZoneInfo("Asia/Shanghai")
    tick_dt = datetime(2025, 1, 1, 9, 30, 0, tzinfo=china_tz)
    tick = _StubTick(
        symbol=vt_symbol,
        last_price=100.0,
        volume=1,
        datetime=tick_dt,
        bid_price_1=99.9,
        ask_price_1=100.1,
    )

    cb(tick)
    # Return immediately; adapter supervisor will treat this as clean end
