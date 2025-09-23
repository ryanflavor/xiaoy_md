from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from src.application.services import MarketDataService, ServiceDependencies
from src.domain.models import MarketDataSubscription, MarketTick
from src.domain.ports import DataRepositoryPort, MarketDataPort, MessagePublisherPort


class _Repo(DataRepositoryPort):
    async def save_tick(self, _tick: MarketTick) -> None:  # pragma: no cover - not used
        return None

    async def get_latest_tick(
        self, _symbol: str
    ) -> MarketTick | None:  # pragma: no cover
        return None

    async def save_subscription(
        self, _subscription: MarketDataSubscription
    ) -> None:  # pragma: no cover
        return None

    async def get_active_subscriptions(
        self,
    ) -> list[MarketDataSubscription]:  # pragma: no cover
        return []


class _Pub(MessagePublisherPort):
    def __init__(self) -> None:
        self.published: list[tuple[str, dict]] = []

    async def connect(self) -> None:  # pragma: no cover
        return None

    async def disconnect(self) -> None:  # pragma: no cover
        return None

    async def publish(self, topic: str, data: dict) -> None:
        self.published.append((topic, data))

    async def health_check(self) -> bool:  # pragma: no cover
        return True


class _MD(MarketDataPort):
    def __init__(self, symbol: str, tz: str) -> None:
        self._symbol = symbol
        self._tz = ZoneInfo(tz)

    async def connect(self) -> None:  # pragma: no cover
        return None

    async def disconnect(self) -> None:  # pragma: no cover
        return None

    async def subscribe(
        self, symbol: str
    ) -> MarketDataSubscription:  # pragma: no cover
        return MarketDataSubscription(
            subscription_id="s-1", symbol=symbol, exchange="CFFEX"
        )

    async def unsubscribe(self, _subscription_id: str) -> None:  # pragma: no cover
        return None

    async def receive_ticks(self):  # type: ignore[no-untyped-def]
        yield MarketTick(
            symbol=self._symbol,
            price=Decimal("123.45"),
            timestamp=datetime(2025, 1, 1, 0, 0, 0, tzinfo=self._tz),
        )


@pytest.mark.asyncio
async def test_subject_and_payload_with_exchange_and_timezone_conversion() -> None:
    md = _MD(symbol="IF2312.CFFEX", tz="UTC")
    pub = _Pub()
    svc = MarketDataService(
        ports=ServiceDependencies(
            market_data=md,
            publisher=pub,
            repository=_Repo(),
        )
    )

    await svc.process_market_data()

    assert len(pub.published) == 1
    topic, payload = pub.published[0]

    # Subject naming must follow market.tick.{exchange}.{symbol}
    assert topic == "market.tick.CFFEX.IF2312"

    # Payload must include exchange and vnpy vt_symbol
    assert payload["exchange"] == "CFFEX"
    assert payload["symbol"] == "IF2312"
    assert payload["vt_symbol"] == "IF2312.CFFEX"

    # Timestamp must be serialized with +08:00 offset (Asia/Shanghai)
    assert payload["timestamp"].endswith("+08:00")
