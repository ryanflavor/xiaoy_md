"""Domain models for the Market Data Service.

This module contains the core business domain models.
All models are immutable as per coding standards.
"""

from datetime import datetime
from decimal import Decimal
import re
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator

CHINA_TZ = ZoneInfo("Asia/Shanghai")


def _now_china() -> datetime:
    return datetime.now(CHINA_TZ)


class InvalidSymbolError(ValueError):
    """Raised when a trading symbol is invalid."""

    def __init__(self, symbol: str | None = None) -> None:
        """Initialize invalid symbol error."""
        if symbol:
            message = (
                f"Invalid symbol format: {symbol}. "
                "Symbol must start with a letter or number and contain only "
                "letters, numbers, dots, dashes, or underscores (max 30 characters)"
            )
        else:
            message = "Symbol cannot be empty"
        super().__init__(message)


class MarketTick(BaseModel):
    """Immutable domain model representing a market data tick.

    This is the core domain model for market data events.
    """

    model_config = ConfigDict(frozen=True, validate_assignment=True)

    symbol: str = Field(..., description="Trading symbol/instrument identifier")
    price: Decimal = Field(..., description="Current market price")
    volume: Decimal | None = Field(default=None, description="Trade volume")
    timestamp: datetime = Field(..., description="Time when the tick was generated")
    bid: Decimal | None = Field(default=None, description="Current bid price")
    ask: Decimal | None = Field(default=None, description="Current ask price")

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, v: str) -> str:
        """Validate trading symbol format.

        Accepts common trading symbol formats including vnpy vt_symbol:
        - vnpy vt_symbol: symbol.exchange (e.g., rb2401.SHFE, IF2312.CFFEX)
        - Chinese futures: Product code + YYMM (e.g., rb2401, IF2312, cu2403)
        - Stock symbols: 1-8 letters/numbers (e.g., AAPL, 600000.SH)
        - Futures: Symbol with month/year code (e.g., CL2312, ESH24)
        - Currency pairs: Two 3-letter codes (e.g., EURUSD, GBPJPY)
        - Crypto: Base-Quote format (e.g., BTC-USD, ETH-USDT)
        """
        if not v or not v.strip():
            raise InvalidSymbolError

        # Remove any whitespace but preserve original case for flexibility
        v = v.strip()

        # Pattern matches common trading symbol formats including vnpy
        # Allows letters (upper and lower), numbers, dots, dashes, and underscores
        # First char can be letter or number (for Chinese stock codes like 600000)
        pattern = r"^[A-Za-z0-9][A-Za-z0-9.\-_]{0,29}$"

        if not re.match(pattern, v):
            raise InvalidSymbolError(v)

        return v

    def __str__(self) -> str:
        """Return string representation of the market tick."""
        return f"MarketTick({self.symbol}@{self.price})"


class MarketDataSubscription(BaseModel):
    """Immutable domain model representing a market data subscription.

    Used to track which symbols are being subscribed to.
    """

    model_config = ConfigDict(frozen=True, validate_assignment=True)

    subscription_id: str = Field(..., description="Unique subscription identifier")
    symbol: str = Field(..., description="Symbol to subscribe to")
    exchange: str = Field(..., description="Exchange where the symbol is traded")
    created_at: datetime = Field(
        default_factory=_now_china, description="Subscription creation time"
    )
    active: bool = Field(default=True, description="Whether subscription is active")

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, v: str) -> str:
        """Validate trading symbol format.

        Uses the same validation as MarketTick for consistency.
        Supports vnpy vt_symbol format and various trading symbols.
        """
        if not v or not v.strip():
            raise InvalidSymbolError

        v = v.strip()
        pattern = r"^[A-Za-z0-9][A-Za-z0-9.\-_]{0,29}$"

        if not re.match(pattern, v):
            raise InvalidSymbolError(v)

        return v

    def __str__(self) -> str:
        """Return string representation of the subscription."""
        status = "active" if self.active else "inactive"
        return f"Subscription({self.subscription_id}: {self.symbol} [{status}])"
