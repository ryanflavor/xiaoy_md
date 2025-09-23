"""Application services for the Market Data Service.

This module contains the application layer services that orchestrate
domain logic and coordinate between different ports.
"""

import asyncio
from collections import defaultdict, deque
import contextlib
from dataclasses import dataclass
from datetime import datetime
import logging
import math
import time
from typing import Any
from zoneinfo import ZoneInfo

from src.application.observability import PrometheusMetricsExporter
from src.domain.models import MarketDataSubscription, MarketTick
from src.domain.ports import DataRepositoryPort, MarketDataPort, MessagePublisherPort

logger = logging.getLogger(__name__)
CHINA_TZ = ZoneInfo("Asia/Shanghai")


class RateLimitError(RuntimeError):
    """Raised when rate limit is exceeded."""

    def __init__(self) -> None:
        """Initialize rate limit error."""
        super().__init__("Rate limit exceeded")


class ConfigurationError(RuntimeError):
    """Raised when configuration is invalid."""

    def __init__(self, message: str = "Port not configured") -> None:
        """Initialize configuration error."""
        super().__init__(message)


@dataclass(slots=True)
class RateLimitConfig:
    window_seconds: float | None = None
    max_requests: int | None = None


@dataclass(slots=True)
class MetricsConfig:
    window_seconds: float = 5.0
    report_interval_seconds: float | None = None


@dataclass(slots=True)
class ServiceDependencies:
    market_data: MarketDataPort | None = None
    publisher: MessagePublisherPort | None = None
    repository: DataRepositoryPort | None = None
    metrics_exporter: PrometheusMetricsExporter | None = None


class MarketDataService:
    """Application service for handling market data operations.

    This service orchestrates the flow of market data from external sources
    to message publishing and storage.
    """

    # Rate limit configuration constants
    RATE_LIMIT_WINDOW_SECONDS = 60.0
    RATE_LIMIT_MAX_REQUESTS = 50

    def __init__(
        self,
        *,
        ports: ServiceDependencies | None = None,
        rate_limits: RateLimitConfig | None = None,
        metrics: MetricsConfig | None = None,
    ) -> None:
        """Initialize the market data service with optional dependencies."""
        dependencies = ports or ServiceDependencies()
        self.market_data_port = dependencies.market_data
        self.publisher_port = dependencies.publisher
        self.repository_port = dependencies.repository
        self._subscriptions: dict[str, MarketDataSubscription] = {}
        self._subscription_symbol_by_id: dict[str, str] = {}
        self._subscription_last_seen: dict[str, datetime] = {}
        self._metrics_exporter = dependencies.metrics_exporter

        rate_config = rate_limits or RateLimitConfig()
        metrics_config = metrics or MetricsConfig()

        # Allow instance-specific rate limit overrides for operational workflows
        if rate_config.window_seconds is not None and rate_config.window_seconds > 0:
            self.RATE_LIMIT_WINDOW_SECONDS = float(rate_config.window_seconds)
        if rate_config.max_requests is not None and rate_config.max_requests > 0:
            self.RATE_LIMIT_MAX_REQUESTS = int(rate_config.max_requests)

        # Simple rate limiting implementation
        self._subscribe_timestamps: deque[float] = deque(
            maxlen=self.RATE_LIMIT_MAX_REQUESTS
        )
        self._unsubscribe_timestamps: deque[float] = deque(
            maxlen=self.RATE_LIMIT_MAX_REQUESTS
        )
        self._rate_limit_window = float(self.RATE_LIMIT_WINDOW_SECONDS)
        self._rate_limit_max = int(self.RATE_LIMIT_MAX_REQUESTS)

        # Observability counters and reporter state (Story 2.4.4)
        self._published_total: int = 0
        self._failed_publishes_total: int = 0
        # Keep recent publish timestamps (monotonic) for rolling-window MPS
        # Size bounded to avoid unbounded growth in extreme loads; 10x window as a guard.
        maxlen = max(100, int((metrics_config.window_seconds or 5.0) * 10))
        self._publish_timestamps: deque[float] = deque(maxlen=maxlen)
        self._latency_samples: deque[tuple[float, float]] = deque(maxlen=maxlen * 10)
        self._metrics_window_seconds = float(metrics_config.window_seconds or 5.0)
        # Default interval equals window unless explicitly overridden
        self._metrics_report_interval_seconds = (
            float(metrics_config.report_interval_seconds)
            if metrics_config.report_interval_seconds is not None
            else self._metrics_window_seconds
        )
        self._metrics_task: asyncio.Task[None] | None = None
        self._last_metrics_published_total: int = 0
        self._last_metrics_dropped_total: int = 0
        self._last_metrics_failed_total: int = 0
        self._error_totals: defaultdict[tuple[str, str], int] = defaultdict(int)

    def _check_rate_limit(self, timestamps: deque[float]) -> bool:
        """Check if an operation is allowed under rate limiting.

        Args:
            timestamps: Deque of recent operation timestamps

        Returns:
            True if operation is allowed, False if rate limit exceeded

        """
        now = time.monotonic()
        cutoff = now - self._rate_limit_window

        # Count recent requests within the window
        recent_count = sum(1 for ts in timestamps if ts > cutoff)

        if recent_count >= self._rate_limit_max:
            logger.warning(
                "Rate limit exceeded",
                extra={
                    "limit": self._rate_limit_max,
                    "window": self._rate_limit_window,
                },
            )
            return False

        # Add current timestamp
        timestamps.append(now)
        return True

    async def initialize(self) -> None:
        """Initialize the service and connect to external systems."""
        logger.info("Initializing Market Data Service")

        if self.market_data_port:
            await self.market_data_port.connect()
            logger.info("Connected to market data source")

        if self.publisher_port:
            await self.publisher_port.connect()
            logger.info("Connected to message publisher")

        if self.repository_port:
            # Load existing active subscriptions
            subscriptions = await self.repository_port.get_active_subscriptions()
            for sub in subscriptions:
                self._subscriptions[sub.subscription_id] = sub
                vt_symbol = self._subscription_key_from_parts(sub.symbol, sub.exchange)
                self._subscription_symbol_by_id[sub.subscription_id] = vt_symbol
                self._subscription_last_seen.setdefault(vt_symbol, sub.created_at)
            logger.info(f"Loaded {len(subscriptions)} active subscriptions")

        # Start metrics reporter loop (non-blocking)
        self._start_metrics_reporter()

    async def shutdown(self) -> None:
        """Shutdown the service and disconnect from external systems."""
        logger.info("Shutting down Market Data Service")

        # Stop metrics reporter
        task = self._metrics_task
        if task is not None:
            try:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            finally:
                self._metrics_task = None

        if self.market_data_port:
            await self.market_data_port.disconnect()
            logger.info("Disconnected from market data source")

        if self.publisher_port:
            await self.publisher_port.disconnect()
            logger.info("Disconnected from message publisher")

    async def subscribe_to_symbol(self, symbol: str) -> MarketDataSubscription:
        """Subscribe to market data for a specific symbol.

        Args:
            symbol: Trading symbol to subscribe to

        Returns:
            MarketDataSubscription object representing the subscription

        Raises:
            RuntimeError: If rate limit exceeded or port not configured

        """
        # Check rate limit
        if not self._check_rate_limit(self._subscribe_timestamps):
            raise RateLimitError

        if not self.market_data_port:
            raise ConfigurationError

        subscription = await self.market_data_port.subscribe(symbol)
        self._subscriptions[subscription.subscription_id] = subscription
        vt_symbol = self._subscription_key_from_parts(
            subscription.symbol, subscription.exchange
        )
        self._subscription_symbol_by_id[subscription.subscription_id] = vt_symbol
        self._subscription_last_seen.setdefault(vt_symbol, subscription.created_at)

        if self.repository_port:
            await self.repository_port.save_subscription(subscription)

        logger.info(f"Subscribed to {symbol} with ID {subscription.subscription_id}")
        return subscription

    async def unsubscribe(self, subscription_id: str) -> None:
        """Unsubscribe from market data.

        Args:
            subscription_id: ID of the subscription to cancel

        Raises:
            RuntimeError: If rate limit exceeded

        """
        # Check rate limit
        if not self._check_rate_limit(self._unsubscribe_timestamps):
            raise RateLimitError

        if subscription_id not in self._subscriptions:
            logger.warning(f"Subscription {subscription_id} not found")
            return

        if self.market_data_port:
            await self.market_data_port.unsubscribe(subscription_id)

        vt_symbol = self._subscription_symbol_by_id.pop(subscription_id, None)
        if vt_symbol is not None:
            self._subscription_last_seen.pop(vt_symbol, None)

        del self._subscriptions[subscription_id]
        logger.info(f"Unsubscribed from {subscription_id}")

    async def process_market_data(self) -> None:
        """Process incoming market data ticks.

        This method continuously processes incoming market data,
        publishes it to the message broker, and stores it.
        """
        if not self.market_data_port:
            logger.warning("Market data port not configured, skipping processing")
            return

        logger.info("Starting market data processing")
        # Ensure metrics reporter is running even when initialize() wasn't called
        self._start_metrics_reporter()

        async for tick in self.market_data_port.receive_ticks():
            await self._process_tick(tick)

    async def _process_tick(self, tick: MarketTick) -> None:
        """Process a single market data tick.

        Args:
            tick: MarketTick to process

        """
        logger.debug(f"Processing tick: {tick}")

        latency_ms = self._measure_latency_ms(tick)
        self._latency_samples.append((time.monotonic(), latency_ms))

        self._mark_subscription_activity(tick)

        # Publish to message broker
        if self.publisher_port:
            try:
                topic, payload = self._build_publish_payload(tick)
                await self.publisher_port.publish(topic, payload)
                self._published_total += 1
                self._publish_timestamps.append(time.monotonic())
            except Exception as e:
                self._failed_publishes_total += 1
                logger.error(f"Failed to publish tick: {e}", exc_info=True)
                self._record_error(component="publisher", severity="critical")

        # Store tick
        if self.repository_port:
            try:
                await self.repository_port.save_tick(tick)
            except Exception as e:
                logger.error(f"Failed to save tick: {e}", exc_info=True)
                self._record_error(component="repository", severity="error")

    def _build_publish_payload(self, tick: MarketTick) -> tuple[str, dict[str, Any]]:
        payload = dict(tick.vnpy) if tick.vnpy else {}
        vt_symbol = payload.get("vt_symbol") or tick.symbol

        symbol_field = payload.get("symbol")
        base_symbol = self._derive_base_symbol(
            payload.get("base_symbol") or symbol_field, vt_symbol
        )
        exchange = self._derive_exchange(payload, symbol_field, vt_symbol)

        derived = {
            "base_symbol": base_symbol,
            "symbol_field": symbol_field,
            "exchange": exchange,
            "vt_symbol": vt_symbol,
        }

        self._enrich_payload(payload, tick, derived)
        topic = f"market.tick.{exchange}.{base_symbol}"
        return topic, payload

    @staticmethod
    def _derive_base_symbol(base_symbol: Any, vt_symbol: str) -> str:
        if isinstance(base_symbol, str) and base_symbol:
            if "." in base_symbol:
                return base_symbol.split(".", 1)[0]
            return base_symbol

        vt_token = str(vt_symbol)
        return vt_token.split(".", 1)[0] if "." in vt_token else vt_token

    @staticmethod
    def _derive_exchange(
        payload: dict[str, Any], symbol_field: Any, vt_symbol: str
    ) -> str:
        exchange = payload.get("exchange")
        if exchange:
            return str(exchange)

        if isinstance(symbol_field, str) and "." in symbol_field:
            return symbol_field.split(".", 1)[1]
        if isinstance(vt_symbol, str) and "." in vt_symbol:
            return vt_symbol.split(".", 1)[1]
        return "UNKNOWN"

    @staticmethod
    def _enrich_payload(
        payload: dict[str, Any], tick: MarketTick, derived: dict[str, Any]
    ) -> None:
        base_symbol = str(derived["base_symbol"])
        symbol_field = derived.get("symbol_field")
        exchange = str(derived["exchange"])
        vt_symbol = str(derived["vt_symbol"])

        payload.setdefault("vt_symbol", vt_symbol)
        payload.setdefault("base_symbol", base_symbol)
        if isinstance(symbol_field, str) and symbol_field:
            payload.setdefault("symbol", symbol_field)
        else:
            payload.setdefault("symbol", base_symbol)

        payload.setdefault("exchange", exchange)
        ts_china = tick.timestamp.astimezone(CHINA_TZ)
        payload.setdefault("datetime", ts_china.isoformat())
        payload.setdefault("timestamp", ts_china.isoformat())
        payload.setdefault("last_price", float(tick.price))
        payload["price"] = str(tick.price)
        if tick.volume is not None:
            payload["volume"] = str(tick.volume)
        if tick.bid is not None:
            payload.setdefault("bid_price_1", float(tick.bid))
            payload["bid"] = str(tick.bid)
        if tick.ask is not None:
            payload.setdefault("ask_price_1", float(tick.ask))
            payload["ask"] = str(tick.ask)
        payload.setdefault("source", payload.get("source", "ctp"))

    async def health_check(self) -> dict[str, bool]:
        """Check the health of all connected services.

        Returns:
            Dictionary with health status of each port

        """
        health = {}

        if self.publisher_port:
            try:
                health["publisher"] = await self.publisher_port.health_check()
            except (AttributeError, TypeError):
                health["publisher"] = False

        # Add more health checks for other ports as needed

        return health

    # Testing helper methods - provide controlled access for testing
    def get_rate_limit_status(self, operation: str = "subscribe") -> dict:
        """Get current rate limit status for testing purposes.

        Args:
            operation: Either 'subscribe' or 'unsubscribe'

        Returns:
            dict: Status including current count and whether limit is reached

        """
        timestamps = (
            self._subscribe_timestamps
            if operation == "subscribe"
            else self._unsubscribe_timestamps
        )
        now = time.time()
        cutoff = now - self._rate_limit_window
        recent_count = sum(1 for ts in timestamps if ts > cutoff)

        return {
            "current_count": recent_count,
            "max_allowed": self._rate_limit_max,
            "window_seconds": self._rate_limit_window,
            "is_limited": recent_count >= self._rate_limit_max,
        }

    def simulate_rate_limit_state(self, operation: str, count: int) -> None:
        """Set rate limit state for testing purposes.

        Args:
            operation: Either 'subscribe' or 'unsubscribe'
            count: Number of recent requests to simulate

        """
        if operation == "subscribe":
            timestamps = self._subscribe_timestamps
        else:
            timestamps = self._unsubscribe_timestamps

        timestamps.clear()
        now = time.time()
        for _ in range(count):
            timestamps.append(now)

    # ---- Observability: Metrics reporter (Story 2.4.4) ----
    def _start_metrics_reporter(self) -> None:
        if self._metrics_task is not None:
            return

        async def _reporter() -> None:
            await asyncio.sleep(min(1.0, self._metrics_report_interval_seconds))
            while True:
                self._emit_metrics_snapshot()
                await asyncio.sleep(self._metrics_report_interval_seconds)

        self._metrics_task = asyncio.create_task(_reporter())

    def _emit_metrics_snapshot(self) -> None:
        # Compute windowed MPS using monotonic timestamps
        now = time.monotonic()
        cutoff = now - self._metrics_window_seconds
        recent = [ts for ts in self._publish_timestamps if ts >= cutoff]
        mps = (
            (len(recent) / self._metrics_window_seconds)
            if self._metrics_window_seconds > 0
            else 0.0
        )

        dropped_total, queue_size, queue_capacity, queue_fill_pct = (
            self._adapter_metrics()
        )
        nats_connected = self._publisher_connected()
        latency_p99 = self._compute_latency_p99(cutoff)

        published_delta = self._published_total - self._last_metrics_published_total
        dropped_delta = dropped_total - self._last_metrics_dropped_total
        failed_delta = self._failed_publishes_total - self._last_metrics_failed_total
        self._last_metrics_published_total = self._published_total
        self._last_metrics_dropped_total = dropped_total
        self._last_metrics_failed_total = self._failed_publishes_total

        active_subscriptions = len(self._subscriptions)

        log_extra = {
            "event": "mps_report",
            "window_seconds": self._metrics_window_seconds,
            "mps_window": round(mps, 3),
            "published_total": self._published_total,
            "published_delta": published_delta,
            "dropped_total": dropped_total,
            "dropped_delta": dropped_delta,
            "failed_total": self._failed_publishes_total,
            "failed_delta": failed_delta,
            "active_subscriptions": active_subscriptions,
            "queue_size": queue_size,
            "queue_capacity": queue_capacity,
            "queue_fill_pct": queue_fill_pct,
            "nats_connected": nats_connected,
            "latency_ms_p99": latency_p99,
        }
        logger.info(
            (
                "MPS report | window=%ss mps_window=%.3f published_total=%d "
                "published_delta=%d dropped_total=%d dropped_delta=%d "
                "failed_total=%d failed_delta=%d active_subscriptions=%d "
                "queue_size=%s queue_capacity=%s queue_fill_pct=%s nats_connected=%s "
                "latency_ms_p99=%.3f"
            ),
            log_extra["window_seconds"],
            log_extra["mps_window"],
            log_extra["published_total"],
            log_extra["published_delta"],
            log_extra["dropped_total"],
            log_extra["dropped_delta"],
            log_extra["failed_total"],
            log_extra["failed_delta"],
            log_extra["active_subscriptions"],
            log_extra["queue_size"],
            log_extra["queue_capacity"],
            log_extra["queue_fill_pct"],
            log_extra["nats_connected"],
            log_extra["latency_ms_p99"],
            extra=log_extra,
        )

        exporter = self._metrics_exporter
        if exporter is not None:
            exporter.observe_throughput(mps)
            exporter.observe_latency_p99(latency_p99)
            exporter.observe_active_subscriptions(active_subscriptions)

    async def list_active_subscriptions(self) -> list[dict[str, object]]:
        """Return a snapshot of active subscriptions and their activity."""
        snapshot: list[dict[str, object]] = []
        for sub in self._subscriptions.values():
            vt_symbol = self._subscription_symbol_by_id.get(sub.subscription_id)
            if vt_symbol is None:
                vt_symbol = self._subscription_key_from_parts(sub.symbol, sub.exchange)
            last_seen = self._subscription_last_seen.get(vt_symbol)
            snapshot.append(
                {
                    "subscription_id": sub.subscription_id,
                    "symbol": vt_symbol,
                    "base_symbol": sub.symbol,
                    "exchange": sub.exchange,
                    "created_at": sub.created_at.astimezone(CHINA_TZ).isoformat(),
                    "active": sub.active,
                    "last_tick_at": (
                        last_seen.astimezone(CHINA_TZ).isoformat()
                        if last_seen
                        else None
                    ),
                }
            )

        snapshot.sort(key=lambda item: str(item.get("symbol", "")))
        return snapshot

    @staticmethod
    def _subscription_key_from_parts(symbol: str, exchange: str) -> str:
        exchange_value = exchange or "UNKNOWN"
        base_symbol = symbol or "UNKNOWN"
        return f"{base_symbol}.{exchange_value}"

    def _mark_subscription_activity(self, tick: MarketTick) -> None:
        """Update last-seen activity for the subscription associated with the tick."""
        vt_symbol = self._resolve_tick_symbol(tick)
        if not vt_symbol:
            return
        try:
            ts_china = tick.timestamp.astimezone(CHINA_TZ)
        except (AttributeError, ValueError):  # pragma: no cover - defensive
            ts_china = datetime.now(CHINA_TZ)
        self._subscription_last_seen[vt_symbol] = ts_china

    def _resolve_tick_symbol(self, tick: MarketTick) -> str | None:
        """Resolve a vt_symbol style identifier from a tick payload."""
        payload = tick.vnpy or {}
        vt_symbol = str(payload.get("vt_symbol") or tick.symbol or "").strip()
        if not vt_symbol:
            return None
        if "." in vt_symbol:
            return vt_symbol
        exchange = str(payload.get("exchange") or "UNKNOWN").strip() or "UNKNOWN"
        return f"{vt_symbol}.{exchange}"

    # Testing helper to fetch current metrics snapshot
    def get_metrics_snapshot(self) -> dict[str, float | int | bool]:
        now = time.monotonic()
        cutoff = now - self._metrics_window_seconds
        recent = [ts for ts in self._publish_timestamps if ts >= cutoff]
        mps = (
            (len(recent) / self._metrics_window_seconds)
            if self._metrics_window_seconds > 0
            else 0.0
        )

        dropped_total, _, _, _ = self._adapter_metrics()
        nats_connected = self._publisher_connected()

        return {
            "window_seconds": self._metrics_window_seconds,
            "mps_window": round(mps, 3),
            "published_total": self._published_total,
            "dropped_total": dropped_total,
            "failed_total": self._failed_publishes_total,
            "nats_connected": nats_connected,
        }

    def emit_metrics_snapshot(self) -> None:
        """Emit a metrics snapshot immediately (testing helper)."""
        self._emit_metrics_snapshot()

    def _adapter_metrics(
        self,
    ) -> tuple[int, int | None, int | None, float | None]:
        port = self.market_data_port
        if port is None:
            return 0, None, None, None

        def _safe_attr(attr: str) -> int | None:
            try:
                value = getattr(port, attr, None)
                if value is None:
                    return None
                return int(value)
            except AttributeError:
                return None
            except Exception:  # noqa: BLE001
                return None

        dropped_total = _safe_attr("dropped_ticks") or 0
        queue_size = _safe_attr("tick_queue_size")
        queue_capacity = _safe_attr("tick_queue_capacity")
        queue_fill_pct = None
        if queue_size is not None and queue_capacity:
            queue_fill_pct = round((queue_size / queue_capacity) * 100.0, 2)
        return dropped_total, queue_size, queue_capacity, queue_fill_pct

    def _publisher_connected(self) -> bool:
        publisher = self.publisher_port
        if publisher is None:
            return False
        try:
            return bool(publisher.connected)  # type: ignore[attr-defined]
        except AttributeError:
            return False
        except Exception:  # noqa: BLE001
            return False

    def _measure_latency_ms(self, tick: MarketTick) -> float:
        """Compute processing latency relative to tick timestamp."""
        ts = tick.timestamp.astimezone(CHINA_TZ)
        now_ts = datetime.now(CHINA_TZ)
        diff_ms = (now_ts - ts).total_seconds() * 1000.0
        if diff_ms < 0:
            return 0.0
        return diff_ms

    def _compute_latency_p99(self, cutoff: float) -> float:
        """Return 99th percentile latency for samples newer than cutoff."""
        samples = self._latency_samples
        while samples and samples[0][0] < cutoff:
            samples.popleft()
        if not samples:
            return 0.0
        # Extract latencies and sort to compute percentile deterministically.
        values = sorted(lat for _, lat in samples)
        if not values:
            return 0.0
        rank = max(0, min(len(values) - 1, math.ceil(0.99 * len(values)) - 1))
        return values[rank]

    def _record_error(self, *, component: str, severity: str, count: int = 1) -> None:
        """Track error totals and propagate to external exporters."""
        if count <= 0:
            return

        key = (component, severity)
        self._error_totals[key] += count
        exporter = self._metrics_exporter
        if exporter is not None:
            exporter.increment_error(
                component=component, severity=severity, count=count
            )


class TickIngestService:
    """Async service that bridges MarketDataPort to a generic publisher.

    Minimal ingest used by the live composition entry. Publisher only needs a
    `publish_tick(tick)` coroutine method; this avoids coupling to transport.
    """

    def __init__(self, market_data, publisher) -> None:  # type: ignore[no-untyped-def]
        """Initialize the ingest bridge.

        Args:
            market_data: Source implementing `connect`, `disconnect`, and `receive_ticks()`.
            publisher: Target exposing async `publish_tick(tick)`.

        """
        self._market_data = market_data
        self._publisher = publisher
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        await self._market_data.connect()

        async def _run() -> None:
            async for tick in self._market_data.receive_ticks():
                if hasattr(self._publisher, "publish_tick"):
                    await self._publisher.publish_tick(tick)

        self._task = asyncio.create_task(_run())

    async def stop(self) -> None:
        task = self._task
        if task is not None:
            try:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            finally:
                self._task = None
        await self._market_data.disconnect()
