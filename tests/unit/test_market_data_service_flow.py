from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

import pytest

from src.application.services import MarketDataService, RateLimitError
from src.domain.models import MarketDataSubscription, MarketTick
from src.domain.ports import DataRepositoryPort, MarketDataPort, MessagePublisherPort

if TYPE_CHECKING:  # type-only imports
    from collections.abc import AsyncIterator


class _Repo(DataRepositoryPort):
    def __init__(self) -> None:
        self.saved_subs: list[MarketDataSubscription] = []
        self.saved_ticks: list[MarketTick] = []

    async def save_tick(self, tick: MarketTick) -> None:
        self.saved_ticks.append(tick)

    async def get_latest_tick(
        self, symbol: str
    ) -> MarketTick | None:  # pragma: no cover
        # Return last matching symbol to exercise the argument and avoid linter warnings
        for t in reversed(self.saved_ticks):
            if t.symbol == symbol:
                return t
        return None

    async def save_subscription(self, subscription: MarketDataSubscription) -> None:
        self.saved_subs.append(subscription)

    async def get_active_subscriptions(self) -> list[MarketDataSubscription]:
        return []


class _Pub(MessagePublisherPort):
    def __init__(self) -> None:
        self.connected = False
        self.published: list[tuple[str, dict[str, Any]]] = []

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False

    async def publish(self, topic: str, data: dict) -> None:
        self.published.append((topic, data))

    async def health_check(self) -> bool:
        return True


class _MD(MarketDataPort):
    def __init__(self) -> None:
        self.connected = False
        tz = ZoneInfo("Asia/Shanghai")
        self._ticks: list[MarketTick] = [
            MarketTick(symbol="rb2401", price=Decimal("2"), timestamp=datetime.now(tz))
        ]

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False

    async def subscribe(self, symbol: str) -> MarketDataSubscription:
        return MarketDataSubscription(
            subscription_id="sub-1", symbol=symbol, exchange="SHFE"
        )

    async def unsubscribe(self, subscription_id: str) -> None:  # pragma: no cover
        # Touch argument to satisfy linters without altering behavior
        if not isinstance(subscription_id, str):
            raise TypeError

    async def receive_ticks(self) -> AsyncIterator[MarketTick]:
        for t in self._ticks:
            yield t


@pytest.mark.asyncio
async def test_market_data_service_sub_unsub_and_process_flow() -> None:
    md = _MD()
    pub = _Pub()
    repo = _Repo()

    svc = MarketDataService(
        market_data_port=md, publisher_port=pub, repository_port=repo
    )

    await svc.initialize()

    sub = await svc.subscribe_to_symbol("rb2401")
    assert sub.subscription_id == "sub-1"

    await svc.process_market_data()
    assert len(pub.published) > 0
    # With no exchange in symbol, expect UNKNOWN exchange in subject per story 2.3
    assert pub.published[0][0] == "market.tick.UNKNOWN.rb2401"

    await svc.unsubscribe("sub-1")
    await svc.shutdown()


@pytest.mark.asyncio
async def test_market_data_service_rate_limit_blocks_subscribe() -> None:
    svc = MarketDataService(
        market_data_port=_MD(), publisher_port=_Pub(), repository_port=_Repo()
    )
    # Simulate limit reached
    svc.simulate_rate_limit_state("subscribe", svc.RATE_LIMIT_MAX_REQUESTS)
    with pytest.raises(RateLimitError):
        await svc.subscribe_to_symbol("rb2401")


@pytest.mark.asyncio
async def test_service_integration_with_ctp_adapter(ctp_settings=None) -> None:
    """AC4: Verify MarketDataService integrates with CTPGatewayAdapter for subscribe.

    Uses real adapter with no live connector; ensures normal interaction
    without affecting other flows.
    """
    # Lazy import to avoid heavy dependencies at module import time
    from src.config import AppSettings
    from src.infrastructure.ctp_adapter import CTPGatewayAdapter

    settings = ctp_settings or AppSettings(
        app_name="test-service",
        nats_client_id="test-client",
        ctp_broker_id="9999",
        ctp_user_id="u001",
        ctp_password="secret-pass",  # pragma: allowlist secret (test fixture value)
        ctp_md_address="127.0.0.1:5001",
        ctp_td_address="tcp://127.0.0.1:5002",
        ctp_app_id="appx",
        ctp_auth_code="authy",  # pragma: allowlist secret (test fixture value)
    )

    adapter = CTPGatewayAdapter(settings)
    svc = MarketDataService(market_data_port=adapter)

    sub = await svc.subscribe_to_symbol("rb2401.SHFE")
    assert sub.symbol == "rb2401"
    assert sub.exchange == "SHFE"
    assert sub.subscription_id

    # Unsubscribe via service; should not raise
    await svc.unsubscribe(sub.subscription_id)
