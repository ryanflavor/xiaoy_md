"""Integration tests for Story 2.1 CTP Gateway Adapter.

Covers P1 integration scenarios from QA plan:
- 2.1-INT-001: connect() then disconnect() joins without deadlock
- 2.1-INT-002: worker exits on shutdown event set during disconnect()
- 2.1-INT-003: failure→restart path with expected backoff; final stop
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from pydantic import SecretStr
import pytest

from src.config import AppSettings
from src.infrastructure.ctp_adapter import CTPGatewayAdapter, RetryPolicy

pytestmark = [pytest.mark.integration]


@pytest.fixture
def ctp_settings() -> AppSettings:
    return AppSettings(
        app_name="test-service",
        nats_client_id="test-client",
        ctp_broker_id="9999",
        ctp_user_id="u001",
        ctp_password=SecretStr("secret-pass"),  # pragma: allowlist secret
        ctp_md_address="127.0.0.1:5001",
        ctp_td_address="tcp://127.0.0.1:5002",
        ctp_app_id="appx",
        ctp_auth_code=SecretStr("authy"),
    )


@pytest.mark.timeout(5)
@pytest.mark.asyncio
async def test_disconnect_joins_cleanly(ctp_settings: AppSettings):
    """2.1-INT-001: connect() then disconnect() joins without deadlock."""
    run_ticks = {"count": 0}

    def gateway_runner(_: dict[str, Any], should_shutdown) -> None:
        while not should_shutdown():
            run_ticks["count"] += 1
            time.sleep(0.01)

    adapter = CTPGatewayAdapter(ctp_settings, gateway_connect=gateway_runner)
    await adapter.connect()
    await asyncio.sleep(0.05)
    await adapter.disconnect()
    assert run_ticks["count"] > 0


@pytest.mark.timeout(5)
@pytest.mark.asyncio
async def test_worker_exits_on_shutdown(ctp_settings: AppSettings):
    """2.1-INT-002: worker exits when shutdown event is set during disconnect()."""
    run_ticks = {"count": 0, "stopped": False}

    def gateway_runner(_: dict[str, Any], should_shutdown) -> None:
        while not should_shutdown():
            run_ticks["count"] += 1
            time.sleep(0.01)
        run_ticks["stopped"] = True

    adapter = CTPGatewayAdapter(ctp_settings, gateway_connect=gateway_runner)
    await adapter.connect()
    await asyncio.sleep(0.05)
    await adapter.disconnect()
    await asyncio.sleep(0.02)
    assert run_ticks["stopped"] is True


def test_failure_then_restart_then_stop(ctp_settings: AppSettings):
    """2.1-INT-003: failure→restart path observed with expected backoff; final stop."""

    def failing_gateway(_: dict[str, Any], __) -> None:
        raise RuntimeError

    sleeps: list[float] = []

    def record_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    policy = RetryPolicy(
        base_backoff=0.01, multiplier=2.0, max_backoff=0.04, max_retries=3
    )
    adapter = CTPGatewayAdapter(
        ctp_settings,
        gateway_connect=failing_gateway,
        retry_policy=policy,
        sleep_fn=record_sleep,
    )

    adapter._supervisor()  # Run inline for determinism  # noqa: SLF001

    assert sleeps == [0.01, 0.02, 0.04]
