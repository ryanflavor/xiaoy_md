"""Application services for the Market Data Service.

This module contains the application layer services that orchestrate
domain logic and coordinate between different ports.
"""

from collections import deque
import logging
import time

from src.domain.models import MarketDataSubscription, MarketTick
from src.domain.ports import DataRepositoryPort, MarketDataPort, MessagePublisherPort

logger = logging.getLogger(__name__)


class RateLimitError(RuntimeError):
    """Raised when rate limit is exceeded."""


class ConfigurationError(RuntimeError):
    """Raised when configuration is invalid."""


class MarketDataService:
    """Application service for handling market data operations.

    This service orchestrates the flow of market data from external sources
    to message publishing and storage.
    """

    def __init__(
        self,
        market_data_port: MarketDataPort | None = None,
        publisher_port: MessagePublisherPort | None = None,
        repository_port: DataRepositoryPort | None = None,
    ):
        """Initialize the market data service with optional ports.

        Args:
            market_data_port: Port for receiving market data
            publisher_port: Port for publishing messages
            repository_port: Port for data persistence

        """
        self.market_data_port = market_data_port
        self.publisher_port = publisher_port
        self.repository_port = repository_port
        self._subscriptions: dict[str, MarketDataSubscription] = {}

        # Simple rate limiting implementation
        self._subscribe_timestamps: deque[float] = deque(maxlen=50)
        self._unsubscribe_timestamps: deque[float] = deque(maxlen=50)
        self._rate_limit_window = 60.0  # 60 second window
        self._rate_limit_max = 50  # Max 50 requests per window

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

    async def shutdown(self) -> None:
        """Shutdown the service and disconnect from external systems."""
        logger.info("Shutting down Market Data Service")

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
                topic = f"market.{tick.symbol}"
                data = {
                    "symbol": tick.symbol,
                    "price": str(tick.price),
                    "volume": str(tick.volume) if tick.volume else None,
                    "timestamp": tick.timestamp.isoformat(),
                    "bid": str(tick.bid) if tick.bid else None,
                    "ask": str(tick.ask) if tick.ask else None,
                }
                await self.publisher_port.publish(topic, data)
            except Exception as e:
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
