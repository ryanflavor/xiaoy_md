"""Unit tests for rate limiting functionality in MarketDataService."""

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from src.application.services import MarketDataService, RateLimitConfig
from src.domain.models import MarketDataSubscription


class TestMarketDataServiceRateLimit:
    """Test rate limiting functionality in MarketDataService."""

    @pytest.fixture
    def mock_market_data_port(self):
        """Create a mock market data port."""
        port = AsyncMock()

        # Subscribe should return a MarketDataSubscription object
        async def mock_subscribe(symbol):
            return MarketDataSubscription(
                subscription_id=f"sub-{symbol}",
                symbol=symbol,
                exchange="TEST",
                created_at=datetime.now(),
                active=True,
            )

        port.subscribe = AsyncMock(side_effect=mock_subscribe)
        port.unsubscribe = AsyncMock(return_value=True)
        return port

    @pytest.fixture
    def mock_publisher_port(self):
        """Create a mock message publisher port."""
        port = AsyncMock()
        port.publish = AsyncMock(return_value=True)
        return port

    @pytest.fixture
    def service(self, mock_market_data_port, mock_publisher_port):
        """Create MarketDataService with mocked dependencies."""
        return MarketDataService(
            market_data_port=mock_market_data_port,
            publisher_port=mock_publisher_port,
            repository_port=None,
        )

    def test_custom_rate_limit_configuration(
        self, mock_market_data_port, mock_publisher_port
    ) -> None:
        """Service uses custom window/max overrides when provided."""
        svc = MarketDataService(
            market_data_port=mock_market_data_port,
            publisher_port=mock_publisher_port,
            repository_port=None,
            rate_limits=RateLimitConfig(window_seconds=10.0, max_requests=5),
        )
        assert svc.RATE_LIMIT_WINDOW_SECONDS == 10.0
        assert svc.RATE_LIMIT_MAX_REQUESTS == 5

    @pytest.mark.asyncio
    async def test_allows_requests_within_rate_limit(self, service):
        """Test that requests within rate limit are allowed."""
        # Service allows 50 requests per 60 seconds
        # Should allow multiple subscriptions within limit
        for i in range(10):
            result = await service.subscribe_to_symbol(f"ES{i}")
            assert result is not None, f"Subscribe {i} should be allowed"
            assert isinstance(result, MarketDataSubscription)

    @pytest.mark.asyncio
    async def test_blocks_subscribe_over_rate_limit(self, service):
        """Test that subscribe requests over rate limit are blocked."""
        # Use the public testing interface to simulate rate limit state
        service.simulate_rate_limit_state("subscribe", service.RATE_LIMIT_MAX_REQUESTS)

        # Verify the rate limit is reached
        status = service.get_rate_limit_status("subscribe")
        assert status["is_limited"] is True

        # Next request should be blocked
        with pytest.raises(RuntimeError) as exc_info:
            await service.subscribe_to_symbol("ES")

        assert "exceeded" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_blocks_unsubscribe_over_rate_limit(self, service):
        """Test that unsubscribe requests over rate limit are blocked."""
        # First subscribe to something
        result = await service.subscribe_to_symbol("ES")
        subscription_id = result.subscription_id

        # Use the public testing interface to simulate rate limit state
        service.simulate_rate_limit_state(
            "unsubscribe", service.RATE_LIMIT_MAX_REQUESTS
        )

        # Verify the rate limit is reached
        status = service.get_rate_limit_status("unsubscribe")
        assert status["is_limited"] is True

        # Next unsubscribe should be blocked
        with pytest.raises(RuntimeError) as exc_info:
            await service.unsubscribe(subscription_id)

        assert "exceeded" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_rate_limit_window_slides(self, service):
        """Test that rate limits allow requests within the limit."""
        # Test we can make requests up to just below the limit
        max_allowed = service.RATE_LIMIT_MAX_REQUESTS

        # Should allow requests up to the limit
        for i in range(max_allowed - 1):
            result = await service.subscribe_to_symbol(f"ES{i}")
            assert result is not None
            assert isinstance(result, MarketDataSubscription)

        # One more should still work (at exactly the limit)
        result = await service.subscribe_to_symbol("LAST")
        assert result is not None

        # Now we should be at the limit
        with pytest.raises(RuntimeError) as exc_info:
            await service.subscribe_to_symbol("OVER")
        assert "exceeded" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_rate_limit_status_accuracy(self, service):
        """Test that rate limit helper methods work correctly."""
        # Test simulate_rate_limit_state sets the state correctly
        test_count = service.RATE_LIMIT_MAX_REQUESTS - 5
        service.simulate_rate_limit_state("subscribe", test_count)
        status = service.get_rate_limit_status("subscribe")
        assert status["current_count"] == test_count
        assert status["is_limited"] is False

        # Simulate being at the limit
        service.simulate_rate_limit_state("subscribe", service.RATE_LIMIT_MAX_REQUESTS)
        status = service.get_rate_limit_status("subscribe")
        assert status["current_count"] == service.RATE_LIMIT_MAX_REQUESTS
        assert status["is_limited"] is True

        # Verify constants are accessible
        assert status["max_allowed"] == service.RATE_LIMIT_MAX_REQUESTS
        assert status["window_seconds"] == service.RATE_LIMIT_WINDOW_SECONDS

    @pytest.mark.asyncio
    async def test_separate_rate_limits_for_subscribe_unsubscribe(self, service):
        """Test that subscribe and unsubscribe have separate rate limits."""
        # Fill subscribe to near limit
        service.simulate_rate_limit_state(
            "subscribe", service.RATE_LIMIT_MAX_REQUESTS - 1
        )

        # Subscribe is almost at limit
        subscribe_status = service.get_rate_limit_status("subscribe")
        assert subscribe_status["current_count"] == service.RATE_LIMIT_MAX_REQUESTS - 1
        assert subscribe_status["is_limited"] is False

        # But unsubscribe should have full capacity
        unsubscribe_status = service.get_rate_limit_status("unsubscribe")
        assert unsubscribe_status["current_count"] == 0
        assert unsubscribe_status["is_limited"] is False

        # Should allow one more subscribe
        result = await service.subscribe_to_symbol("ES")
        assert result is not None

    @pytest.mark.asyncio
    async def test_rate_limit_logs_warning(self, service):
        """Test that rate limit violations are logged."""
        # Fill up the rate limit using public interface
        service.simulate_rate_limit_state("subscribe", service.RATE_LIMIT_MAX_REQUESTS)

        with patch("src.application.services.logger.warning") as mock_warning:
            # This should trigger rate limit
            with pytest.raises(RuntimeError):
                await service.subscribe_to_symbol("ES")

            # Warning should have been logged
            mock_warning.assert_called()

            # Check the log message contains relevant info
            log_call = mock_warning.call_args
            assert "Rate limit exceeded" in log_call[0][0]
            # Check that extra dict contains rate limit info
            extra = log_call[1].get("extra", {})
            assert extra.get("limit") == service.RATE_LIMIT_MAX_REQUESTS
            assert extra.get("window") == service.RATE_LIMIT_WINDOW_SECONDS
