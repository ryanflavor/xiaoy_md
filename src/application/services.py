"""Application services for the Market Data Service.

This module contains the application layer services that orchestrate
domain logic and coordinate between different ports.
"""

import asyncio
from collections import deque
import contextlib
from dataclasses import dataclass
import logging
import time
from zoneinfo import ZoneInfo

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
        market_data_port: MarketDataPort | None = None,
        publisher_port: MessagePublisherPort | None = None,
        repository_port: DataRepositoryPort | None = None,
        *,
        rate_limits: RateLimitConfig | None = None,
        metrics: MetricsConfig | None = None,
    ):
        """Initialize the market data service with optional ports.

        Args:
            market_data_port: Port for receiving market data.
            publisher_port: Port for publishing messages.
            repository_port: Port for data persistence.
            rate_limits: Optional rate limit overrides.
            metrics: Optional metrics reporting configuration.

        """
        self.market_data_port = market_data_port
        self.publisher_port = publisher_port
        self.repository_port = repository_port
        self._subscriptions: dict[str, MarketDataSubscription] = {}

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

        # Publish to message broker
        if self.publisher_port:
            try:
                payload = dict(tick.vnpy) if tick.vnpy else {}
                vt_symbol = payload.get("vt_symbol") or tick.symbol
                base_symbol = payload.get("symbol") or vt_symbol.split(".", 1)[0]
                exchange = payload.get("exchange") or (
                    vt_symbol.split(".", 1)[1] if "." in vt_symbol else "UNKNOWN"
                )

                # Ensure canonical fields are present
                payload.setdefault("vt_symbol", vt_symbol)
                payload.setdefault("symbol", base_symbol)
                payload.setdefault("exchange", exchange)
                ts_china = tick.timestamp.astimezone(CHINA_TZ)
                payload.setdefault("datetime", ts_china.isoformat())
                payload.setdefault("timestamp", ts_china.isoformat())
                payload.setdefault("last_price", float(tick.price))
                if tick.volume is not None:
                    payload.setdefault("volume", float(tick.volume))
                if tick.bid is not None:
                    payload.setdefault("bid_price_1", float(tick.bid))
                if tick.ask is not None:
                    payload.setdefault("ask_price_1", float(tick.ask))
                payload.setdefault("source", payload.get("source", "ctp"))

                topic = f"market.tick.{exchange}.{base_symbol}"

                await self.publisher_port.publish(topic, payload)
                # Success path: record counters/timestamps for MPS
                self._published_total += 1
                self._publish_timestamps.append(time.monotonic())
            except Exception as e:
                # Failure path: increment failure counter
                self._failed_publishes_total += 1
                logger.error(f"Failed to publish tick: {e}", exc_info=True)

        # Store tick
        if self.repository_port:
            try:
                await self.repository_port.save_tick(tick)
            except Exception as e:
                logger.error(f"Failed to save tick: {e}", exc_info=True)

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
        }
        logger.info(
            (
                "MPS report | window=%ss mps_window=%.3f published_total=%d "
                "published_delta=%d dropped_total=%d dropped_delta=%d "
                "failed_total=%d failed_delta=%d active_subscriptions=%d "
                "queue_size=%s queue_capacity=%s queue_fill_pct=%s nats_connected=%s"
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
            extra=log_extra,
        )

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
