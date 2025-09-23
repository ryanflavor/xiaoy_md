"""Prometheus observability helpers for the market data service."""

from __future__ import annotations

from dataclasses import dataclass
import logging

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    generate_latest,
    start_http_server,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class IngestMetricLabels:
    """Static labels applied to ingest metrics."""

    feed: str
    account: str


class PrometheusMetricsExporter:
    """Wrap Prometheus objects for the ingest pipeline."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        labels: IngestMetricLabels,
        registry: CollectorRegistry | None = None,
        start_http: bool = True,
    ) -> None:
        """Initialize exporter with provided networking parameters and labels."""
        self._labels = labels
        self._registry = registry or CollectorRegistry()
        self._throughput_gauge = Gauge(
            "md_throughput_mps",
            "Market data throughput measured in messages per second",
            ("feed", "account"),
            registry=self._registry,
        )
        self._latency_p99_gauge = Gauge(
            "md_latency_ms_p99",
            "P99 market data processing latency in milliseconds",
            ("feed",),
            registry=self._registry,
        )
        self._active_subscriptions_gauge = Gauge(
            "md_active_subscriptions",
            "Number of active market data subscriptions",
            ("feed",),
            registry=self._registry,
        )
        self._error_counter = Counter(
            "md_error_count",
            "Count of critical errors emitted by the market data service",
            ("component", "severity"),
            registry=self._registry,
        )

        if start_http:
            try:
                start_http_server(port, addr=host, registry=self._registry)
                logger.info(
                    "Prometheus metrics exporter online",
                    extra={"host": host, "port": port},
                )
            except OSError as exc:
                logger.warning(
                    "prometheus_exporter_start_failed",
                    extra={"host": host, "port": port, "error": str(exc)},
                )

    @property
    def registry(self) -> CollectorRegistry:
        """Return underlying collector registry (primarily for tests)."""
        return self._registry

    @property
    def labels(self) -> IngestMetricLabels:
        """Return the static labels for the exporter."""
        return self._labels

    def observe_throughput(self, mps: float) -> None:
        """Record current throughput gauge."""
        value = max(mps, 0.0)
        self._throughput_gauge.labels(
            feed=self._labels.feed, account=self._labels.account
        ).set(value)

    def observe_latency_p99(self, p99_ms: float) -> None:
        """Record the latency P99 in milliseconds."""
        value = max(p99_ms, 0.0)
        self._latency_p99_gauge.labels(feed=self._labels.feed).set(value)

    def observe_active_subscriptions(self, count: int) -> None:
        """Expose active subscription count."""
        self._active_subscriptions_gauge.labels(feed=self._labels.feed).set(
            max(count, 0)
        )

    def increment_error(self, *, component: str, severity: str, count: int = 1) -> None:
        """Increment error counter for a component/severity pair."""
        if count <= 0:
            return
        self._error_counter.labels(component=component, severity=severity).inc(count)

    def scrape(self) -> bytes:
        """Return raw exposition format bytes for assertions."""
        return generate_latest(self._registry)


__all__ = [
    "IngestMetricLabels",
    "PrometheusMetricsExporter",
]
