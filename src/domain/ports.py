"""Domain ports (interfaces) for the Market Data Service.

This module defines the port interfaces that the domain uses to interact
with external systems. These are abstract base classes that will be
implemented in the infrastructure layer.
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from src.domain.models import MarketDataSubscription, MarketTick


class MarketDataPort(ABC):
    """Port for receiving market data from external sources.

    This interface is implemented by infrastructure adapters
    that connect to market data providers.
    """

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to the market data source."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Close connection to the market data source."""

    @abstractmethod
    async def subscribe(self, symbol: str) -> MarketDataSubscription:
        """Subscribe to market data for a specific symbol.

        Args:
            symbol: Trading symbol to subscribe to

        Returns:
            MarketDataSubscription object representing the subscription

        """

    @abstractmethod
    async def unsubscribe(self, subscription_id: str) -> None:
        """Unsubscribe from market data.

        Args:
            subscription_id: ID of the subscription to cancel

        """

    @abstractmethod
    def receive_ticks(self) -> AsyncIterator[MarketTick]:
        """Receive market data ticks as they arrive.

        Yields:
            MarketTick objects as they are received

        """


class MessagePublisherPort(ABC):
    """Port for publishing messages to external systems.

    This interface is implemented by infrastructure adapters
    that publish data to message brokers like NATS.
    """

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to the message broker."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Close connection to the message broker."""

    @abstractmethod
    async def publish(self, topic: str, data: dict) -> None:
        """Publish a message to a specific topic.

        Args:
            topic: Topic/subject to publish to
            data: Message data as a dictionary

        """

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the connection is healthy.

        Returns:
            True if connection is healthy, False otherwise

        """


class DataRepositoryPort(ABC):
    """Port for data persistence operations.

    This interface is implemented by infrastructure adapters
    that handle data storage and retrieval.
    """

    @abstractmethod
    async def save_tick(self, tick: MarketTick) -> None:
        """Save a market tick to storage.

        Args:
            tick: MarketTick to save

        """

    @abstractmethod
    async def get_latest_tick(self, symbol: str) -> MarketTick | None:
        """Retrieve the latest tick for a symbol.

        Args:
            symbol: Trading symbol to query

        Returns:
            Latest MarketTick for the symbol, or None if not found

        """

    @abstractmethod
    async def save_subscription(self, subscription: MarketDataSubscription) -> None:
        """Save a subscription to storage.

        Args:
            subscription: MarketDataSubscription to save

        """

    @abstractmethod
    async def get_active_subscriptions(self) -> list[MarketDataSubscription]:
        """Retrieve all active subscriptions.

        Returns:
            List of active MarketDataSubscription objects

        """
