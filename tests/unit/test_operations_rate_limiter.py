"""Tests for operational RateLimiter used in full-feed workflow."""

from __future__ import annotations

import asyncio

import pytest

from src.operations.full_feed_subscription import RateLimiter


class FakeClock:
    """Deterministic clock helper for testing."""

    def __init__(self) -> None:
        """Initialize deterministic clock at time zero."""
        self._now = 0.0

    def now(self) -> float:
        return self._now

    def advance(self, delta: float) -> None:
        self._now += delta


@pytest.mark.asyncio
async def test_rate_limiter_disabled_allows_immediate_acquire() -> None:
    limiter = RateLimiter(max_per_window=0, window_seconds=0)
    await limiter.acquire(100)
    assert limiter.current_load == 0


@pytest.mark.asyncio
async def test_rate_limiter_blocks_until_capacity() -> None:
    clock = FakeClock()

    async def fake_sleep(duration: float) -> None:
        clock.advance(duration)

    limiter = RateLimiter(
        max_per_window=2,
        window_seconds=5.0,
        now_fn=clock.now,
        sleep_coro=fake_sleep,
    )

    await limiter.acquire(2)
    assert limiter.current_load == 2

    task = asyncio.create_task(limiter.acquire(1))
    await asyncio.sleep(0)
    assert clock.now() == pytest.approx(5.0)
    await task
    assert limiter.current_load == 1

    limiter.release(1)
    assert limiter.current_load == 0
