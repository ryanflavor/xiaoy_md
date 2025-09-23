from __future__ import annotations

import asyncio
from datetime import datetime
from decimal import Decimal
import logging
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

import prometheus_client.parser as prometheus_parser
import pytest

from src.application.observability import (
    IngestMetricLabels,
    PrometheusMetricsExporter,
)
from src.application.services import (
    MarketDataService,
    MetricsConfig,
    ServiceDependencies,
)
from src.domain.models import MarketDataSubscription, MarketTick
from src.domain.ports import MarketDataPort, MessagePublisherPort

if TYPE_CHECKING:  # type-only imports
    from collections.abc import AsyncIterator


class _DropAwarePort(MarketDataPort):
    """Fake market data port that yields predefined ticks and exposes drops."""

    def __init__(self, ticks: list[MarketTick]) -> None:
        self._ticks = ticks
        self.connected = False
        self.dropped_ticks = 2  # simulate adapter having dropped some ticks

    async def connect(self) -> None:  # pragma: no cover - trivial
        self.connected = True

    async def disconnect(self) -> None:  # pragma: no cover - trivial
        self.connected = False

    async def subscribe(
        self, symbol: str
    ) -> MarketDataSubscription:  # pragma: no cover
        return MarketDataSubscription(
            subscription_id="sub-1", symbol=symbol, exchange="SHFE"
        )

    async def unsubscribe(
        self, _subscription_id: str
    ) -> None:  # pragma: no cover - unused
        return None

    async def receive_ticks(self) -> AsyncIterator[MarketTick]:
        for t in self._ticks:
            yield t


class SimulatedPublishError(RuntimeError):
    """Raised to simulate a single publish failure."""


class _FlakyPublisher(MessagePublisherPort):
    """Fake publisher that fails once then succeeds to exercise counters."""

    def __init__(self) -> None:
        self.connected = False
        self._first = True
        self.published: list[tuple[str, dict[str, Any]]] = []

    async def connect(self) -> None:  # pragma: no cover - trivial
        self.connected = True

    async def disconnect(self) -> None:  # pragma: no cover - trivial
        self.connected = False

    async def publish(self, topic: str, data: dict) -> None:
        if self._first:
            self._first = False
            raise SimulatedPublishError
        self.published.append((topic, data))

    async def health_check(self) -> bool:  # pragma: no cover - trivial
        return True


@pytest.mark.asyncio
async def test_metrics_counters_and_reporter_smoke(
    caplog: pytest.LogCaptureFixture,
) -> None:
    tz = ZoneInfo("Asia/Shanghai")
    ticks = [
        MarketTick(
            symbol="rb2401.SHFE", price=Decimal("2"), timestamp=datetime.now(tz)
        ),
        MarketTick(
            symbol="rb2401.SHFE", price=Decimal("3"), timestamp=datetime.now(tz)
        ),
    ]

    md = _DropAwarePort(ticks)
    pub = _FlakyPublisher()

    exporter = PrometheusMetricsExporter(
        host="127.0.0.1",
        port=9401,
        labels=IngestMetricLabels(feed="primary", account="acct"),
        start_http=False,
    )

    svc = MarketDataService(
        ports=ServiceDependencies(
            market_data=md,
            publisher=pub,
            metrics_exporter=exporter,
        ),
        metrics=MetricsConfig(window_seconds=0.1, report_interval_seconds=0.1),
    )

    caplog.set_level(logging.INFO)
    await svc.initialize()
    await svc.process_market_data()

    # Allow reporter to emit at least one snapshot
    await asyncio.sleep(0.2)
    svc.emit_metrics_snapshot()

    snap = svc.get_metrics_snapshot()
    assert snap["published_total"] == 1  # one success
    assert snap["failed_total"] == 1  # one failure
    assert snap["dropped_total"] == 2  # from drop-aware port

    # Validate a log record with expected structured fields exists
    records = [r for r in caplog.records if getattr(r, "event", "") == "mps_report"]
    assert records, "Expected at least one mps_report log"
    r = records[-1]
    # Smoke-check required fields
    for field in (
        "window_seconds",
        "mps_window",
        "published_total",
        "dropped_total",
        "failed_total",
        "nats_connected",
    ):
        assert hasattr(r, field), f"missing field: {field}"

    metrics_text = exporter.scrape().decode("utf-8")
    families = {
        family.name: family
        for family in prometheus_parser.text_string_to_metric_families(metrics_text)
    }

    throughput_samples = families["md_throughput_mps"].samples
    assert throughput_samples
    throughput_sample = throughput_samples[0]
    assert throughput_sample.labels["feed"] == "primary"
    assert throughput_sample.labels["account"] == "acct"
    assert throughput_sample.value >= 0.0

    latency_samples = families["md_latency_ms_p99"].samples
    assert latency_samples
    assert latency_samples[0].labels["feed"] == "primary"

    error_samples = families["md_error_count"].samples
    assert error_samples
    err_sample = error_samples[0]
    assert err_sample.labels["component"] == "publisher"
    assert err_sample.labels["severity"] == "critical"
    assert err_sample.value == 1.0

    await svc.shutdown()
