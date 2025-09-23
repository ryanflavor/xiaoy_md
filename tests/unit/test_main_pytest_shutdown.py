from __future__ import annotations

import asyncio

from nats.errors import NoServersError
import pytest

import src.__main__ as main_module

pytestmark = pytest.mark.filterwarnings(
    "ignore:coroutine 'AsyncMockMixin._execute_mock_call' was never awaited"
)


class _DummyService:
    def __init__(self, *_args, **_kwargs) -> None:
        self._inited = False

    async def initialize(self) -> None:
        self._inited = True

    async def shutdown(self) -> None:
        self._inited = False


@pytest.mark.asyncio
async def test_run_service_auto_shutdown_when_pytest_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensures run_service exits via PYTEST_CURRENT_TEST auto-shutdown path."""
    # Make the PYTEST_CURRENT_TEST flag present to trigger call_later shutdown
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "1")

    # Prevent real NATS connections by substituting a no-op service
    monkeypatch.setattr(main_module, "MarketDataService", _DummyService)

    # Ensure environment uses test behavior via env flag
    monkeypatch.setenv("ENVIRONMENT", "test")

    class _DummyPublisher:
        def __init__(self, *_args, **_kwargs) -> None:
            self.retry_config = type("RetryConfig", (), {})()
            self.connection_stats = {
                "connect_attempts": 0,
                "successful_publishes": 0,
                "failed_publishes": 0,
            }

        async def connect(self) -> None:  # pragma: no cover - trivial
            self.connection_stats["connect_attempts"] += 1

        async def disconnect(self) -> None:  # pragma: no cover - trivial
            return None

        def get_connection_stats(self) -> dict[str, int]:
            return self.connection_stats

    class _DummyRPC:
        async def start(self) -> None:  # pragma: no cover - trivial
            return None

        async def stop(self) -> None:  # pragma: no cover - trivial
            return None

    monkeypatch.setattr(main_module, "NATSPublisher", _DummyPublisher)
    monkeypatch.setattr(main_module, "NATSRPCServer", lambda *_a, **_k: _DummyRPC())

    # Should return within ~1s due to call_later in run_service
    await asyncio.wait_for(main_module.run_service(), timeout=3.0)


class _RaisingService:
    def __init__(self, *_args, **_kwargs) -> None:
        return None

    async def initialize(self) -> None:
        raise NoServersError

    async def shutdown(self) -> None:
        pass


@pytest.mark.asyncio
async def test_run_service_raises_in_non_development(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Initialization error must propagate when not in development environment."""
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setattr(main_module, "MarketDataService", _RaisingService)

    with pytest.raises(NoServersError):
        await main_module.run_service()
