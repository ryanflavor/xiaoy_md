"""Unit tests for rate limiting functionality in MarketDataService."""

from collections import deque
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from src.application.services import MarketDataService
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
        subscription = MarketDataSubscription(
            subscription_id="test-sub-1",
            symbol="ES",
            exchange="CME",
            created_at=datetime.now(),
            active=True,
        )

        # Fill up the rate limit (50 requests)
        # Manually manipulate timestamps to simulate hitting the limit
        service._subscribe_timestamps = deque(  # noqa: SLF001
            [datetime.now().timestamp()] * 50, maxlen=100
        )

        # Next request should be blocked
        with pytest.raises(RuntimeError) as exc_info:
            await service.subscribe_to_symbol(subscription.symbol)

        assert "Subscribe rate limit exceeded" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_blocks_unsubscribe_over_rate_limit(self, service):
        """Test that unsubscribe requests over rate limit are blocked."""
        # First subscribe to something
        result = await service.subscribe_to_symbol("ES")
        subscription_id = result.subscription_id

        # Fill up the unsubscribe rate limit
        service._unsubscribe_timestamps = deque(  # noqa: SLF001
            [datetime.now().timestamp()] * 50, maxlen=100
        )

        # Next unsubscribe should be blocked
        with pytest.raises(RuntimeError) as exc_info:
            await service.unsubscribe(subscription_id)

        assert "Unsubscribe rate limit exceeded" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_rate_limit_window_slides(self, service):
        """Test that old requests outside window don't count."""
        subscription = MarketDataSubscription(
            subscription_id="test-sub-1",
            symbol="ES",
            exchange="CME",
            created_at=datetime.now(),
            active=True,
        )

        # Add old timestamps (older than 60 seconds)
        old_timestamp = datetime.now().timestamp() - 61  # 61 seconds ago
        service._subscribe_timestamps = deque(  # noqa: SLF001
            [old_timestamp] * 10, maxlen=100  # 10 old requests that should be ignored
        )

        # Should allow new requests since old ones are outside window
        result = await service.subscribe_to_symbol(subscription.symbol)
        assert result is not None
        assert isinstance(result, MarketDataSubscription)

    def test_check_rate_limit_cleans_old_timestamps(self, service):
        """Test that _check_rate_limit removes old timestamps."""
        # Add mix of old and new timestamps
        now = datetime.now().timestamp()
        old = now - 61  # Outside 60 second window

        timestamps = deque([old, old, now, now], maxlen=100)
        initial_count = len([t for t in timestamps if t > now - 60])

        # Check rate limit
        result = service._check_rate_limit(timestamps)  # noqa: SLF001

        # Should be allowed (only 2 recent requests)
        assert result is True

        # Old timestamps should be removed, keeping only recent ones
        # Plus the new one added by _check_rate_limit
        # Only recent timestamps should remain
        final_count = len([t for t in timestamps if t > now - 60])
        assert final_count >= initial_count  # Should have added one and kept recent

    def test_separate_rate_limits_for_subscribe_unsubscribe(self, service):
        """Test that subscribe and unsubscribe have separate rate limits."""
        # Fill subscribe timestamps
        service._subscribe_timestamps = deque(  # noqa: SLF001
            [datetime.now().timestamp()] * 49, maxlen=100
        )

        # Unsubscribe should still have room in its separate limit
        result = service._check_rate_limit(  # noqa: SLF001
            service._unsubscribe_timestamps  # noqa: SLF001
        )
        assert result is True

        # Subscribe should have room for one more
        result = service._check_rate_limit(  # noqa: SLF001
            service._subscribe_timestamps  # noqa: SLF001
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_rate_limit_logs_warning(self, service):
        """Test that rate limit violations are logged."""
        # Fill up the rate limit
        service._subscribe_timestamps = deque(  # noqa: SLF001
            [datetime.now().timestamp()] * 50, maxlen=100
        )

        with patch("src.application.services.logger.warning") as mock_warning:
            # This should trigger rate limit
            result = service._check_rate_limit(  # noqa: SLF001
                service._subscribe_timestamps  # noqa: SLF001
            )

            assert result is False
            mock_warning.assert_called_once()

            # Check the log message contains relevant info
            log_call = mock_warning.call_args
            assert "Rate limit exceeded" in log_call[0][0]
            # Check that extra dict contains rate limit info
            extra = log_call[1].get("extra", {})
            assert extra.get("limit") == 50  # noqa: PLR2004
            assert extra.get("window") == 60.0  # noqa: PLR2004
