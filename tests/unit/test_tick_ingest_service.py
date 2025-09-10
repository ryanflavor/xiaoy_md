from __future__ import annotations

import asyncio
from datetime import datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from src.application.services import TickIngestService
from src.domain.models import MarketTick
from src.domain.ports import MarketDataPort


class _FakeMarketData(MarketDataPort):
    def __init__(self) -> None:
        self.connected = False
        self._ticks: list[MarketTick] = [
            MarketTick(
                symbol="rb2401",
                price=Decimal("1"),
                timestamp=datetime.now(ZoneInfo("Asia/Shanghai")),
            )
        ]

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False

    async def subscribe(self, symbol: str):  # pragma: no cover - not used here
        raise NotImplementedError

    async def unsubscribe(self, subscription_id: str) -> None:  # pragma: no cover
        raise NotImplementedError

    async def receive_ticks(self):
        for tick in self._ticks:
            yield tick


class _FakePublisher:
    def __init__(self) -> None:
        self.connected = False
        self.published: list[tuple[str, dict[str, Any]]] = []

    async def publish_tick(self, tick: MarketTick) -> None:
        self.published.append(("tick", {"symbol": tick.symbol}))


@pytest.mark.asyncio
async def test_tick_ingest_service_start_stop_publishes_tick():
    md = _FakeMarketData()
    pub = _FakePublisher()
    service = TickIngestService(md, pub)

    await service.start()
    # give the background task a short slice to consume one tick
    await asyncio.sleep(0.01)
    await service.stop()

    # Our fake publisher records ticks via publish_tick
    assert len(pub.published) >= 1
