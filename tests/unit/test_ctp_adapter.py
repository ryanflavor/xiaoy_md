"""Unit and light integration tests for the CTP Gateway Adapter.

Covers P0 scenarios from QA test design for Story 2.1.
Links to ACs: 1-4
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from typing import Any

import pytest

from src.config import AppSettings
from src.infrastructure.ctp_adapter import (
    CTPGatewayAdapter,
    RetryPolicy,
    normalize_address,
)


@pytest.fixture
def ctp_settings() -> AppSettings:
    """Create test settings including CTP credentials and endpoints."""
    return AppSettings(
        app_name="test-service",
        nats_client_id="test-client",
        ctp_broker_id="9999",
        ctp_user_id="u001",
        ctp_password="secret-pass",  # pragma: allowlist secret (test fixture value)
        ctp_md_address="127.0.0.1:5001",
        ctp_td_address="tcp://127.0.0.1:5002",
        ctp_app_id="appx",
        ctp_auth_code="authy",
    )


class FakeExecutor:
    """Minimal fake executor capturing submitted functions for assertions."""

    def __init__(self) -> None:
        """Initialize container for submitted call records."""
        self.submitted: list[tuple[Any, tuple[Any, ...], dict[str, Any]]] = []

    def submit(self, fn: Any, *args: Any, **kwargs: Any) -> SimpleNamespace:
        self.submitted.append((fn, args, kwargs))
        # Return an object that mimics concurrent.futures.Future minimally
        return SimpleNamespace(cancelled=lambda: False, done=lambda: False)


class TestAC1Contract:
    """AC1: Adapter implements port and exposes required methods."""

    @pytest.mark.asyncio
    async def test_class_initialization(self, ctp_settings: AppSettings):
        adapter = CTPGatewayAdapter(ctp_settings)
        # Basic state
        assert adapter.settings is ctp_settings
        assert adapter.retry_policy.max_retries == 3
        assert adapter.executor is not None

    @pytest.mark.asyncio
    async def test_unimplemented_methods_raise(self, ctp_settings: AppSettings):
        adapter = CTPGatewayAdapter(ctp_settings)
        with pytest.raises(NotImplementedError):
            await adapter.subscribe("rb2401.SHFE")
        with pytest.raises(NotImplementedError):
            await adapter.unsubscribe("sub-1")
        with pytest.raises(NotImplementedError):
            _ = adapter.receive_ticks()


class TestAC2ThreadLifecycle:
    """AC2: connect() submits worker; disconnect joins cleanly."""

    @pytest.mark.asyncio
    async def test_connect_submits_worker(self, ctp_settings: AppSettings):
        fake_exec = FakeExecutor()
        adapter = CTPGatewayAdapter(ctp_settings, executor=fake_exec)  # type: ignore[arg-type]
        await adapter.connect()
        assert len(fake_exec.submitted) == 1
        fn, args, _ = fake_exec.submitted[0]
        assert callable(fn)
        assert args == ()

    @pytest.mark.asyncio
    async def test_disconnect_joins_cleanly(self, ctp_settings: AppSettings):
        run_ticks = {"count": 0}

        def gateway_runner(_: dict[str, Any], shutdown_flag) -> None:
            while not shutdown_flag():
                run_ticks["count"] += 1
                time.sleep(0.02)

        adapter = CTPGatewayAdapter(ctp_settings, gateway_connect=gateway_runner)
        await adapter.connect()
        await asyncio.sleep(0.05)
        await adapter.disconnect()
        assert run_ticks["count"] > 0


class TestAC3SupervisionAndBackoff:
    """AC3: Supervision retries with exponential backoff and structured logs."""

    def test_backoff_sequence_and_retry_cap(
        self, ctp_settings: AppSettings, caplog: pytest.LogCaptureFixture
    ):
        def failing_gateway(_: dict[str, Any], __) -> None:
            raise RuntimeError

        sleeps: list[float] = []

        def fake_sleep(seconds: float) -> None:
            sleeps.append(seconds)

        policy = RetryPolicy(
            base_backoff=0.5, multiplier=2.0, max_backoff=2.0, max_retries=3
        )
        adapter = CTPGatewayAdapter(
            ctp_settings,
            gateway_connect=failing_gateway,
            sleep_fn=fake_sleep,
            retry_policy=policy,
            executor=None,  # Run supervisor inline for deterministic test
        )

        adapter._supervisor()  # noqa: SLF001

        assert sleeps == [0.5, 1.0, 2.0]
        attempts = [getattr(rec, "attempt", None) for rec in caplog.records]
        assert 1 in attempts
        assert 2 in attempts
        assert 3 in attempts
        backoffs = [getattr(rec, "next_backoff", None) for rec in caplog.records]
        assert any(b == 0.5 for b in backoffs)

    def test_new_thread_spawned_each_retry(self, ctp_settings: AppSettings):
        """Ensure a new session is started per retry (fresh thread each attempt)."""

        def failing_gateway(_: dict[str, Any], __) -> None:
            # Raise to force retry; runs inside the session thread
            raise RuntimeError

        adapter = CTPGatewayAdapter(
            ctp_settings,
            gateway_connect=failing_gateway,
            retry_policy=RetryPolicy(
                base_backoff=0.0, multiplier=2.0, max_backoff=0.0, max_retries=3
            ),
            executor=None,
            sleep_fn=lambda _seconds: None,
        )

        adapter._supervisor()  # noqa: SLF001

        # Expect max_retries + 1 sessions (initial attempt + retries)
        assert getattr(adapter, "_session_counter", 0) == 4


class TestAC4ConfigMappingAndNormalization:
    """AC4: Mapping keys and address normalization; secret masking."""

    def test_vnpy_key_mapping(self, ctp_settings: AppSettings):
        adapter = CTPGatewayAdapter(ctp_settings)
        setting = adapter._build_vnpy_setting()  # noqa: SLF001
        assert setting["用户名"] == ctp_settings.ctp_user_id
        assert setting["密码"] == ctp_settings.ctp_password
        assert setting["经纪商代码"] == ctp_settings.ctp_broker_id
        assert setting["交易服务器"].startswith("tcp://")
        assert setting["行情服务器"].startswith("tcp://")
        assert setting["产品名称"] == ctp_settings.ctp_app_id
        assert setting["授权编码"] == ctp_settings.ctp_auth_code

    def test_address_normalization(self):
        assert normalize_address("127.0.0.1:5001") == "tcp://127.0.0.1:5001"
        assert normalize_address("tcp://127.0.0.1:5002") == "tcp://127.0.0.1:5002"
        assert normalize_address("ssl://example:443") == "ssl://example:443"

    def test_to_dict_safe_masks_secrets(self, ctp_settings: AppSettings):
        data = ctp_settings.to_dict_safe()
        assert data["ctp_password"] != ctp_settings.ctp_password
        assert data["ctp_auth_code"] != ctp_settings.ctp_auth_code
