"""Unit tests for the NATS Publisher adapter."""

import asyncio
import json
from unittest.mock import AsyncMock, Mock, patch

from nats.errors import ConnectionClosedError, TimeoutError
import pytest

from src.config import AppSettings
from src.infrastructure.nats_publisher import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitState,
    NATSPublisher,
    RetryConfig,
)


@pytest.fixture
def settings():
    """Create test settings."""
    return AppSettings(
        nats_url="nats://localhost:4222",
        nats_client_id="test-client",
        app_name="test-service",
    )


@pytest.fixture
def retry_config():
    """Create test retry configuration."""
    return RetryConfig(
        max_attempts=3,
        initial_delay=0.1,
        max_delay=1.0,
        exponential_base=2.0,
        jitter=False,
    )


@pytest.fixture
def circuit_breaker_config():
    """Create test circuit breaker configuration."""
    return CircuitBreakerConfig(
        failure_threshold=3, recovery_timeout=1.0, half_open_max_attempts=2
    )


@pytest.fixture
def publisher(settings, retry_config, circuit_breaker_config):
    """Create NATS Publisher instance."""
    return NATSPublisher(settings, retry_config, circuit_breaker_config)


class TestCircuitBreaker:
    """Test CircuitBreaker class."""

    @pytest.mark.asyncio
    async def test_circuit_starts_closed(self):
        """Test circuit breaker starts in CLOSED state."""
        config = CircuitBreakerConfig()
        breaker = CircuitBreaker(config)
        assert breaker.state == CircuitState.CLOSED
        assert await breaker.can_execute() is True

    @pytest.mark.asyncio
    async def test_circuit_opens_after_threshold(self):
        """Test circuit opens after failure threshold."""
        config = CircuitBreakerConfig(failure_threshold=3)
        breaker = CircuitBreaker(config)

        # Record failures up to threshold
        for _ in range(3):
            await breaker.record_failure()

        assert breaker.state == CircuitState.OPEN
        assert await breaker.can_execute() is False

    @pytest.mark.asyncio
    async def test_circuit_transitions_to_half_open(self):
        """Test circuit transitions to HALF_OPEN after recovery timeout."""
        config = CircuitBreakerConfig(failure_threshold=2, recovery_timeout=0.1)
        breaker = CircuitBreaker(config)

        # Open the circuit
        await breaker.record_failure()
        await breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

        # Wait for recovery timeout
        await asyncio.sleep(0.15)

        # Should transition to HALF_OPEN
        assert await breaker.can_execute() is True
        assert breaker.state == CircuitState.HALF_OPEN

    @pytest.mark.asyncio
    async def test_circuit_closes_on_half_open_success(self):
        """Test circuit closes after success in HALF_OPEN state."""
        config = CircuitBreakerConfig()
        breaker = CircuitBreaker(config)
        breaker.state = CircuitState.HALF_OPEN

        await breaker.record_success()
        assert breaker.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_circuit_reopens_on_half_open_failures(self):
        """Test circuit reopens after failures in HALF_OPEN state."""
        config = CircuitBreakerConfig(half_open_max_attempts=2)
        breaker = CircuitBreaker(config)
        breaker.state = CircuitState.HALF_OPEN

        # First failure
        await breaker.record_failure()
        assert breaker.state == CircuitState.HALF_OPEN

        # Second failure - should reopen
        await breaker.record_failure()
        assert breaker.state == CircuitState.OPEN


class TestNATSPublisher:
    """Test NATSPublisher class."""

    @pytest.mark.asyncio
    async def test_connect_success(self, publisher):
        """Test successful connection to NATS."""
        with patch("src.infrastructure.nats_publisher.NATS") as mock_nats_class:
            mock_nc = AsyncMock()
            mock_nats_class.return_value = mock_nc

            await publisher.connect()

            assert publisher._connected is True
            mock_nc.connect.assert_called_once()
            assert publisher._connection_stats["connect_attempts"] == 1

    @pytest.mark.asyncio
    async def test_connect_already_connected(self, publisher):
        """Test connect when already connected."""
        publisher._connected = True
        publisher._nc = Mock()

        with patch("src.infrastructure.nats_publisher.NATS") as mock_nats_class:
            await publisher.connect()
            mock_nats_class.assert_not_called()

    @pytest.mark.asyncio
    async def test_connect_with_retry(self, publisher):
        """Test connection with retry on failure."""
        with patch("src.infrastructure.nats_publisher.NATS") as mock_nats_class:
            mock_nc = AsyncMock()
            mock_nats_class.return_value = mock_nc

            # First attempt fails, second succeeds
            mock_nc.connect.side_effect = [
                ConnectionClosedError("Connection failed"),
                None,
            ]

            await publisher.connect()

            assert publisher._connected is True
            assert mock_nc.connect.call_count == 2
            assert publisher._connection_stats["connect_attempts"] == 2

    @pytest.mark.asyncio
    async def test_connect_max_retries_exceeded(self, publisher):
        """Test connection fails after max retries."""
        with patch("src.infrastructure.nats_publisher.NATS") as mock_nats_class:
            mock_nc = AsyncMock()
            mock_nats_class.return_value = mock_nc
            mock_nc.connect.side_effect = ConnectionClosedError("Connection failed")

            with pytest.raises(ConnectionClosedError):
                await publisher.connect()

            assert publisher._connected is False
            assert mock_nc.connect.call_count == publisher.retry_config.max_attempts

    @pytest.mark.asyncio
    async def test_disconnect(self, publisher):
        """Test graceful disconnection."""
        mock_nc = AsyncMock()
        publisher._nc = mock_nc
        publisher._connected = True

        # Set up health check subscription mock
        mock_subscription = AsyncMock()
        publisher._health_check_subscription = mock_subscription

        await publisher.disconnect()

        assert publisher._connected is False
        assert publisher._nc is None
        mock_subscription.unsubscribe.assert_called_once()
        mock_nc.drain.assert_called_once()
        mock_nc.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_disconnect_not_connected(self, publisher):
        """Test disconnect when not connected."""
        await publisher.disconnect()  # Should not raise

    @pytest.mark.asyncio
    async def test_publish_success(self, publisher):
        """Test successful message publishing."""
        mock_nc = AsyncMock()
        publisher._nc = mock_nc
        publisher._connected = True

        data = {"test": "data"}
        await publisher.publish("test.topic", data)

        expected_message = json.dumps(data).encode()
        mock_nc.publish.assert_called_once_with("test.topic", expected_message)
        assert publisher._connection_stats["successful_publishes"] == 1

    @pytest.mark.asyncio
    async def test_publish_not_connected(self, publisher):
        """Test publish when not connected."""
        with pytest.raises(ConnectionClosedError):
            await publisher.publish("test.topic", {"test": "data"})

    @pytest.mark.asyncio
    async def test_publish_with_retry(self, publisher):
        """Test publish with retry on failure."""
        mock_nc = AsyncMock()
        publisher._nc = mock_nc
        publisher._connected = True

        # First attempt fails, second succeeds
        mock_nc.publish.side_effect = [TimeoutError("Timeout"), None]

        data = {"test": "data"}
        await publisher.publish("test.topic", data)

        assert mock_nc.publish.call_count == 2
        assert publisher._connection_stats["successful_publishes"] == 1

    @pytest.mark.asyncio
    async def test_publish_failure_updates_stats(self, publisher):
        """Test publish failure updates statistics."""
        mock_nc = AsyncMock()
        publisher._nc = mock_nc
        publisher._connected = True
        mock_nc.publish.side_effect = TimeoutError("Timeout")

        with pytest.raises(TimeoutError):
            await publisher.publish("test.topic", {"test": "data"})

        assert publisher._connection_stats["failed_publishes"] == 1

    @pytest.mark.asyncio
    async def test_health_check_healthy(self, publisher):
        """Test health check when connection is healthy."""
        mock_nc = AsyncMock()
        publisher._nc = mock_nc
        publisher._connected = True

        result = await publisher.health_check()

        assert result is True
        mock_nc.flush.assert_called_once_with(timeout=5)

    @pytest.mark.asyncio
    async def test_health_check_not_connected(self, publisher):
        """Test health check when not connected."""
        result = await publisher.health_check()
        assert result is False

    @pytest.mark.asyncio
    async def test_health_check_timeout(self, publisher):
        """Test health check with timeout."""
        mock_nc = AsyncMock()
        publisher._nc = mock_nc
        publisher._connected = True
        mock_nc.flush.side_effect = TimeoutError("Timeout")

        result = await publisher.health_check()

        assert result is False

    @pytest.mark.asyncio
    async def test_setup_health_check_responder(self, publisher):
        """Test health check responder setup."""
        mock_nc = AsyncMock()
        publisher._nc = mock_nc
        publisher._connected = True

        await publisher._setup_health_check_responder()

        mock_nc.subscribe.assert_called_once()
        call_args = mock_nc.subscribe.call_args
        assert call_args[0][0] == "health.check"

    @pytest.mark.asyncio
    async def test_health_check_responder_callback(self, publisher):
        """Test health check responder callback."""
        mock_nc = AsyncMock()
        publisher._nc = mock_nc
        publisher._connected = True

        # Set up the responder
        await publisher._setup_health_check_responder()

        # Get the callback function
        call_args = mock_nc.subscribe.call_args
        callback = call_args.kwargs["cb"]

        # Create mock message
        mock_msg = AsyncMock()

        # Call the callback
        await callback(mock_msg)

        # Verify response was sent
        mock_msg.respond.assert_called_once()
        response_data = json.loads(mock_msg.respond.call_args[0][0])
        assert response_data["service"] == publisher.settings.app_name
        assert "status" in response_data
        assert "timestamp" in response_data

    def test_get_connection_stats(self, publisher):
        """Test getting connection statistics."""
        publisher._connected = True
        publisher._connection_stats["successful_publishes"] = 10
        publisher._connection_stats["failed_publishes"] = 2

        stats = publisher.get_connection_stats()

        assert stats["connected"] is True
        assert stats["successful_publishes"] == 10
        assert stats["failed_publishes"] == 2
        assert stats["circuit_breaker_state"] == CircuitState.CLOSED.value

    @pytest.mark.asyncio
    async def test_create_connection_options_basic(self, publisher):
        """Test basic connection options creation."""
        options = publisher._create_connection_options()

        assert options["servers"] == [publisher.settings.nats_url]
        assert options["name"] == publisher.settings.nats_client_id
        assert "error_cb" in options
        assert "disconnected_cb" in options
        assert "reconnected_cb" in options
        assert "closed_cb" in options

    @pytest.mark.asyncio
    async def test_error_callback(self, publisher):
        """Test error callback updates circuit breaker."""
        error = RuntimeError("Test error")
        await publisher._error_callback(error)

        assert publisher.circuit_breaker.failure_count == 1

    @pytest.mark.asyncio
    async def test_disconnected_callback(self, publisher):
        """Test disconnected callback updates connection state."""
        publisher._connected = True
        await publisher._disconnected_callback()
        assert publisher._connected is False

    @pytest.mark.asyncio
    async def test_reconnected_callback(self, publisher):
        """Test reconnected callback updates state and sets up health check."""
        with patch.object(publisher, "_setup_health_check_responder", new=AsyncMock()):
            await publisher._reconnected_callback()
            assert publisher._connected is True
            publisher._setup_health_check_responder.assert_called_once()

    @pytest.mark.asyncio
    async def test_closed_callback(self, publisher):
        """Test closed callback updates connection state."""
        publisher._connected = True
        await publisher._closed_callback()
        assert publisher._connected is False

    @pytest.mark.asyncio
    async def test_circuit_breaker_integration(self, publisher):
        """Test circuit breaker prevents connections when open."""
        # Force circuit breaker to open
        publisher.circuit_breaker.state = CircuitState.OPEN
        publisher.circuit_breaker.last_failure_time = (
            asyncio.get_event_loop().time()
        )  # Recent failure

        with patch("src.infrastructure.nats_publisher.NATS") as mock_nats_class:
            with pytest.raises(ConnectionClosedError):
                await publisher.connect()
            mock_nats_class.assert_not_called()  # Connection should not be attempted
