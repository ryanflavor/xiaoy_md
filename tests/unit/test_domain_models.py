"""Unit tests for domain models."""

from datetime import datetime
from decimal import Decimal

from pydantic import ValidationError
import pytest

from src.domain.models import MarketDataSubscription, MarketTick


class TestMarketTickValidation:
    """Test validation for MarketTick model."""

    def test_valid_stock_symbol(self):
        """Test valid stock symbols are accepted."""
        tick = MarketTick(
            symbol="AAPL", price=Decimal("150.50"), timestamp=datetime.now()
        )
        assert tick.symbol == "AAPL"

    def test_symbol_lowercase_accepted(self):
        """Test symbols with lowercase are accepted (for vnpy compatibility)."""
        tick = MarketTick(
            symbol="rb2401", price=Decimal("150.50"), timestamp=datetime.now()
        )
        assert tick.symbol == "rb2401"  # Preserves original case

    def test_valid_futures_symbol(self):
        """Test futures symbols are accepted."""
        tick = MarketTick(
            symbol="CL2312", price=Decimal("78.50"), timestamp=datetime.now()
        )
        assert tick.symbol == "CL2312"

    def test_valid_crypto_symbol(self):
        """Test crypto symbols with dashes are accepted."""
        tick = MarketTick(
            symbol="BTC-USD", price=Decimal("45000"), timestamp=datetime.now()
        )
        assert tick.symbol == "BTC-USD"

    def test_empty_symbol_rejected(self):
        """Test empty symbols are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            MarketTick(symbol="", price=Decimal("100"), timestamp=datetime.now())
        assert "Symbol cannot be empty" in str(exc_info.value)

    def test_symbol_starting_with_number_accepted(self):
        """Test symbols starting with numbers are accepted (for Chinese stocks)."""
        tick = MarketTick(
            symbol="600000.SH", price=Decimal("100"), timestamp=datetime.now()
        )
        assert tick.symbol == "600000.SH"

    def test_symbol_with_invalid_chars_rejected(self):
        """Test symbols with invalid characters are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            MarketTick(symbol="ABC@DEF", price=Decimal("100"), timestamp=datetime.now())
        assert "Invalid symbol format" in str(exc_info.value)

    def test_symbol_too_long_rejected(self):
        """Test symbols over 30 characters are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            MarketTick(symbol="A" * 31, price=Decimal("100"), timestamp=datetime.now())
        assert "Invalid symbol format" in str(exc_info.value)

    def test_vnpy_vt_symbol_format(self):
        """Test vnpy vt_symbol format is accepted."""
        tick = MarketTick(
            symbol="rb2401.SHFE", price=Decimal("3500"), timestamp=datetime.now()
        )
        assert tick.symbol == "rb2401.SHFE"

    def test_chinese_futures_format(self):
        """Test Chinese futures format is accepted."""
        # Test various Chinese futures symbols
        symbols = ["IF2312", "rb2401", "cu2403", "m2405", "SR401"]
        for sym in symbols:
            tick = MarketTick(
                symbol=sym, price=Decimal("1000"), timestamp=datetime.now()
            )
            assert tick.symbol == sym

    def test_immutability(self):
        """Test that MarketTick is immutable."""
        tick = MarketTick(
            symbol="AAPL", price=Decimal("150.50"), timestamp=datetime.now()
        )
        with pytest.raises(ValidationError):
            tick.symbol = "GOOGL"  # type: ignore[misc]


class TestMarketDataSubscriptionValidation:
    """Test validation for MarketDataSubscription model."""

    def test_valid_subscription(self):
        """Test valid subscription creation."""
        sub = MarketDataSubscription(
            subscription_id="sub-123", symbol="AAPL", exchange="NASDAQ"
        )
        assert sub.symbol == "AAPL"
        assert sub.subscription_id == "sub-123"
        assert sub.active is True

    def test_symbol_validation_in_subscription(self):
        """Test symbol validation is applied to subscriptions."""
        sub = MarketDataSubscription(
            subscription_id="sub-123", symbol="eurusd", exchange="FOREX"
        )
        assert sub.symbol == "eurusd"  # Preserves original case for vnpy compatibility

    def test_invalid_symbol_in_subscription_rejected(self):
        """Test invalid symbols are rejected in subscriptions."""
        with pytest.raises(ValidationError) as exc_info:
            MarketDataSubscription(
                subscription_id="sub-123", symbol="@INVALID", exchange="TEST"
            )
        assert "Invalid symbol format" in str(exc_info.value)
