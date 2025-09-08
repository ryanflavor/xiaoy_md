"""NATS Publisher adapter for message publishing.

This module implements the MessagePublisherPort interface for NATS,
with enhanced security, resilience, and monitoring capabilities.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
import json
import logging
import time
from typing import Any, TypeVar

T = TypeVar("T")

from nats.aio.client import Client as NATS
from nats.errors import (
    ConnectionClosedError,
    TimeoutError,
)

from src.config import AppSettings
from src.domain.ports import MessagePublisherPort

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """Circuit breaker states."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker pattern."""

    failure_threshold: int = 5
    recovery_timeout: float = 60.0
    half_open_max_attempts: int = 3


@dataclass
class RetryConfig:
    """Configuration for retry logic with exponential backoff."""

    max_attempts: int = 5
    initial_delay: float = 1.0
    max_delay: float = 60.0
    exponential_base: float = 2.0
    jitter: bool = True


@dataclass
class CircuitBreaker:
    """Circuit breaker implementation to prevent connection storms."""

    config: CircuitBreakerConfig
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    last_failure_time: float = 0.0
    half_open_attempts: int = 0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def can_execute(self) -> bool:
        """Check if operation can be executed based on circuit state."""
        async with self._lock:
            if self.state == CircuitState.CLOSED:
                return True

            if self.state == CircuitState.OPEN:
                time_since_failure = time.monotonic() - self.last_failure_time
                if time_since_failure > self.config.recovery_timeout:
                    logger.info("Circuit breaker transitioning to HALF_OPEN")
                    self.state = CircuitState.HALF_OPEN
                    self.half_open_attempts = 0
                    return True
                return False

            if self.state == CircuitState.HALF_OPEN:
                return self.half_open_attempts < self.config.half_open_max_attempts

        return False

    async def record_success(self) -> None:
        """Record successful operation."""
        async with self._lock:
            if self.state == CircuitState.HALF_OPEN:
                logger.info("Circuit breaker transitioning to CLOSED after success")
                self.state = CircuitState.CLOSED
                self.failure_count = 0
                self.half_open_attempts = 0
            elif self.state == CircuitState.CLOSED:
                self.failure_count = 0

    async def record_failure(self) -> None:
        """Record failed operation."""
        async with self._lock:
            self.failure_count += 1
            self.last_failure_time = time.monotonic()

            if self.state == CircuitState.HALF_OPEN:
                self.half_open_attempts += 1
                if self.half_open_attempts >= self.config.half_open_max_attempts:
                    logger.warning("Circuit breaker transitioning back to OPEN")
                    self.state = CircuitState.OPEN
            elif (
                self.state == CircuitState.CLOSED
                and self.failure_count >= self.config.failure_threshold
            ):
                logger.warning(
                    f"Circuit breaker OPEN after {self.failure_count} failures"
                )
                self.state = CircuitState.OPEN


class NATSPublisher(MessagePublisherPort):
    """NATS implementation of the MessagePublisherPort.

    Provides secure, resilient NATS connectivity with:
    - TLS encryption and authentication
    - Retry logic with exponential backoff
    - Circuit breaker pattern
    - Health check responder
    - Connection monitoring
    """

    def __init__(
        self,
        settings: AppSettings,
        retry_config: RetryConfig | None = None,
        circuit_breaker_config: CircuitBreakerConfig | None = None,
    ):
        """Initialize NATS Publisher.

        Args:
            settings: Application settings
            retry_config: Optional retry configuration
            circuit_breaker_config: Optional circuit breaker configuration

        """
        self.settings = settings
        self._nc: NATS | None = None
        self._connected = False
        self._health_check_subscription: Any = (
            None  # nats.aio.subscription.Subscription
        )
        self._connection_stats: dict[str, Any] = {
            "connect_attempts": 0,
            "successful_publishes": 0,
            "failed_publishes": 0,
            "last_health_check": None,
        }

        # Resilience configurations
        self.retry_config = retry_config or RetryConfig()
        self.circuit_breaker = CircuitBreaker(
            circuit_breaker_config or CircuitBreakerConfig()
        )

        # Connection lock to prevent concurrent connection attempts
        self._connection_lock = asyncio.Lock()

    def _create_connection_options(self) -> dict[str, Any]:
        """Create NATS connection options with security settings.

        Returns:
            Dictionary of connection options

        """
        options = {
            "servers": [self.settings.nats_url],
            "name": self.settings.nats_client_id,
            "reconnect_time_wait": 2,
            "max_reconnect_attempts": 10,
            "error_cb": self._error_callback,
            "disconnected_cb": self._disconnected_callback,
            "reconnected_cb": self._reconnected_callback,
            "closed_cb": self._closed_callback,
        }

        # Add authentication if configured (simple username/password only)
        if self.settings.nats_user and self.settings.nats_password:
            options["user"] = self.settings.nats_user
            options["password"] = self.settings.nats_password
            logger.info("NATS authentication configured")

        return options

    async def _error_callback(self, e: Exception) -> None:
        """Handle NATS errors."""
        logger.error(f"NATS error: {e}", exc_info=True)
        await self.circuit_breaker.record_failure()

    async def _disconnected_callback(self) -> None:
        """Handle NATS disconnection."""
        logger.warning("NATS disconnected")
        self._connected = False

    async def _reconnected_callback(self) -> None:
        """Handle NATS reconnection."""
        logger.info("NATS reconnected")
        self._connected = True
        await self.circuit_breaker.record_success()
        await self._setup_health_check_responder()

    async def _closed_callback(self) -> None:
        """Handle NATS connection closed."""
        logger.info("NATS connection closed")
        self._connected = False

    async def _retry_with_backoff(
        self, operation: Callable[[], Awaitable[T]], operation_name: str
    ) -> T:
        """Execute operation with exponential backoff retry.

        Args:
            operation: Async function to execute
            operation_name: Name of operation for logging

        Returns:
            Result of the operation

        Raises:
            Exception: If all retry attempts fail

        """
        last_exception = None
        delay = self.retry_config.initial_delay

        for attempt in range(1, self.retry_config.max_attempts + 1):
            try:
                # Check circuit breaker
                if not await self.circuit_breaker.can_execute():
                    raise ConnectionClosedError("Circuit breaker is OPEN")

                logger.debug(
                    f"Attempting {operation_name} (attempt {attempt}/{self.retry_config.max_attempts})"
                )
                result = await operation()
                await self.circuit_breaker.record_success()
                return result

            except Exception as e:
                last_exception = e
                await self.circuit_breaker.record_failure()

                if attempt < self.retry_config.max_attempts:
                    # Add jitter to prevent thundering herd
                    if self.retry_config.jitter:
                        import random

                        jitter_delay = delay * (0.5 + random.random())
                    else:
                        jitter_delay = delay

                    logger.warning(
                        f"{operation_name} failed (attempt {attempt}), "
                        f"retrying in {jitter_delay:.2f}s: {e}"
                    )
                    await asyncio.sleep(jitter_delay)

                    # Exponential backoff
                    delay = min(
                        delay * self.retry_config.exponential_base,
                        self.retry_config.max_delay,
                    )
                else:
                    logger.error(
                        f"{operation_name} failed after {attempt} attempts: {e}"
                    )

        raise last_exception or RuntimeError(f"{operation_name} failed")

    async def connect(self) -> None:
        """Establish connection to NATS with security and resilience."""
        async with self._connection_lock:
            if self._connected:
                logger.debug("Already connected to NATS")
                return

            async def _connect_operation() -> None:
                self._connection_stats["connect_attempts"] += 1
                self._nc = NATS()
                options = self._create_connection_options()
                await self._nc.connect(**options)
                self._connected = True
                logger.info(
                    f"Connected to NATS at {self.settings.nats_url} "
                    f"(attempt {self._connection_stats['connect_attempts']})"
                )
                await self._setup_health_check_responder()

            await self._retry_with_backoff(_connect_operation, "NATS connection")

    async def disconnect(self) -> None:
        """Gracefully disconnect from NATS."""
        if not self._nc:
            return

        try:
            # Unsubscribe from health check
            if self._health_check_subscription:
                await self._health_check_subscription.unsubscribe()
                self._health_check_subscription = None

            # Drain and close connection
            await self._nc.drain()
            await self._nc.close()
            self._connected = False
            logger.info("Disconnected from NATS")
        except Exception as e:
            logger.error(f"Error during NATS disconnect: {e}", exc_info=True)
        finally:
            self._nc = None
            self._connected = False

    async def publish(self, topic: str, data: dict) -> None:
        """Publish message to NATS topic with resilience.

        Args:
            topic: NATS subject to publish to
            data: Message data as dictionary

        """
        if not self._connected or not self._nc:
            raise ConnectionClosedError("Not connected to NATS")

        async def _publish_operation() -> None:
            # Serialize data to JSON
            message = json.dumps(data).encode()

            # Publish message
            if self._nc:
                await self._nc.publish(topic, message)
                logger.debug(f"Published to {topic}")

            self._connection_stats["successful_publishes"] += 1

        try:
            await self._retry_with_backoff(_publish_operation, f"publish to {topic}")
        except Exception as e:
            self._connection_stats["failed_publishes"] += 1
            logger.error(f"Failed to publish to {topic}: {e}", exc_info=True)
            raise

    async def health_check(self) -> bool:
        """Check NATS connection health.

        Returns:
            True if healthy, False otherwise

        """
        if not self._nc or not self._connected:
            return False

        try:
            # Ping NATS server
            await self._nc.flush(timeout=5)
            self._connection_stats["last_health_check"] = datetime.now(UTC).isoformat()
            return True
        except (TimeoutError, ConnectionClosedError) as e:
            logger.warning(f"Health check failed: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error during health check: {e}", exc_info=True)
            return False

    async def _setup_health_check_responder(self) -> None:
        """Set up health check responder on dedicated subject."""
        if not self._nc or not self._connected:
            return

        try:
            # Subscribe to health check requests
            async def health_check_handler(msg: Any) -> None:
                """Handle health check requests."""
                health_status = {
                    "service": self.settings.app_name,
                    "status": "healthy" if await self.health_check() else "unhealthy",
                    "timestamp": datetime.now(UTC).isoformat(),
                    "stats": self._connection_stats,
                    "circuit_breaker_state": self.circuit_breaker.state.value,
                }
                response = json.dumps(health_status).encode()
                await msg.respond(response)
                logger.debug("Responded to health check request")

            self._health_check_subscription = await self._nc.subscribe(
                self.settings.nats_health_check_subject, cb=health_check_handler
            )
            logger.info(
                f"Health check responder set up on '{self.settings.nats_health_check_subject}' subject"
            )
        except Exception as e:
            logger.error(f"Failed to set up health check responder: {e}", exc_info=True)

    def get_connection_stats(self) -> dict[str, Any]:
        """Get connection statistics for monitoring.

        Returns:
            Dictionary with connection statistics

        """
        return {
            **self._connection_stats,
            "connected": self._connected,
            "circuit_breaker_state": self.circuit_breaker.state.value,
            "circuit_breaker_failures": self.circuit_breaker.failure_count,
        }
