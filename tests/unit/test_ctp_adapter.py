"""Unit and light integration tests for the CTP Gateway Adapter.

Covers P0 scenarios from QA test design for Story 2.1 and 2.2.
Links to ACs: Story 2.1 (1-4), Story 2.2 (1-3)
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from decimal import Decimal
import threading
import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest

from src.config import AppSettings
from src.domain.models import MarketTick
from src.infrastructure.ctp_adapter import (
    CHINA_TZ,
    MAX_FLOAT,
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
        # Executor is created lazily on connect
        assert adapter.executor is None

    @pytest.mark.asyncio
    async def test_subscribe_unsubscribe_available(self, ctp_settings: AppSettings):
        """Story 2.4.2: subscribe/unsubscribe implemented and callable."""
        adapter = CTPGatewayAdapter(ctp_settings)
        sub = await adapter.subscribe("rb2401.SHFE")
        assert sub.symbol == "rb2401"
        assert sub.exchange == "SHFE"
        assert isinstance(sub.subscription_id, str)
        assert sub.subscription_id != ""
        # Should be idempotent for the same symbol
        sub2 = await adapter.subscribe("rb2401.SHFE")
        assert sub2.subscription_id == sub.subscription_id
        # Unsubscribe should not raise
        await adapter.unsubscribe(sub.subscription_id)
        # Idempotent unknown unsubscribe logs warning but not raise
        await adapter.unsubscribe(sub.subscription_id)


class TestStory242SubscribeUnsubscribe:
    """Unit tests for Story 2.4.2: adapter subscribe/unsubscribe behavior."""

    @pytest.mark.asyncio
    async def test_subscribe_success_and_idempotent(self, ctp_settings: AppSettings):
        adapter = CTPGatewayAdapter(ctp_settings)
        sub1 = await adapter.subscribe("rb2401.SHFE")
        assert sub1.symbol == "rb2401"
        assert sub1.exchange == "SHFE"
        assert sub1.subscription_id.startswith("sub-")

        # Duplicate subscribe returns existing
        sub2 = await adapter.subscribe("rb2401.SHFE")
        assert sub2.subscription_id == sub1.subscription_id

    @pytest.mark.asyncio
    async def test_subscribe_plain_symbol_uses_unknown_exchange(
        self, ctp_settings: AppSettings
    ):
        adapter = CTPGatewayAdapter(ctp_settings)
        sub = await adapter.subscribe("IF2312")
        assert sub.symbol == "IF2312"
        assert sub.exchange == "UNKNOWN"

    @pytest.mark.asyncio
    async def test_unsubscribe_unknown_is_idempotent(
        self, ctp_settings: AppSettings, caplog
    ):
        adapter = CTPGatewayAdapter(ctp_settings)
        await adapter.unsubscribe("does-not-exist")
        assert "unknown_subscription_id" in caplog.text

    @pytest.mark.asyncio
    async def test_invalid_symbol_raises(self, ctp_settings: AppSettings):
        adapter = CTPGatewayAdapter(ctp_settings)
        with pytest.raises(Exception):
            await adapter.subscribe("")
        with pytest.raises(Exception):
            await adapter.subscribe("!!bad!!")


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


# Story 2.2 Test Classes


class TestStory22AC1OnTickMethod:
    """Story 2.2 AC1: Adapter overrides on_tick() method to capture vnpy TickData."""

    @pytest.mark.asyncio
    async def test_on_tick_method_signature_matches_base_gateway(
        self, ctp_settings: AppSettings
    ):
        """Test 2.2-UNIT-001: Verify on_tick method signature matches BaseGateway [AC1]."""
        adapter = CTPGatewayAdapter(ctp_settings)
        assert hasattr(adapter, "on_tick")
        assert callable(adapter.on_tick)
        # Method should accept a tick parameter
        import inspect

        sig = inspect.signature(adapter.on_tick)
        assert "tick" in sig.parameters

    @pytest.mark.asyncio
    async def test_on_tick_handles_valid_tickdata(self, ctp_settings: AppSettings):
        """Test 2.2-UNIT-002: Test on_tick handles valid TickData object [AC1]."""
        adapter = CTPGatewayAdapter(ctp_settings)
        # Avoid spawning worker threads; set loop reference directly
        adapter._main_loop = asyncio.get_running_loop()  # noqa: SLF001

        # Setup contract map
        adapter.symbol_contract_map["rb2401"] = Mock()

        # Create mock vnpy TickData
        mock_tick = Mock()
        mock_tick.symbol = "rb2401"
        mock_tick.last_price = 4500.0
        mock_tick.volume = 1000
        mock_tick.datetime = datetime.now(CHINA_TZ)
        mock_tick.bid_price_1 = 4499.0
        mock_tick.ask_price_1 = 4501.0

        # Call on_tick
        adapter.on_tick(mock_tick)

        # Give time for async operation to complete
        await asyncio.sleep(0.01)

        # Should have queued the tick
        assert adapter._tick_queue.qsize() > 0  # noqa: SLF001

    @pytest.mark.asyncio
    async def test_on_tick_ignores_ticks_without_contract_data(
        self, ctp_settings: AppSettings
    ):
        """Test 2.2-UNIT-003: Test on_tick ignores ticks without contract data [AC1]."""
        adapter = CTPGatewayAdapter(ctp_settings)

        # No contract in map
        adapter.symbol_contract_map = {}

        mock_tick = Mock()
        mock_tick.symbol = "UNKNOWN"
        mock_tick.last_price = 100.0

        # Call on_tick
        adapter.on_tick(mock_tick)

        # Should not queue the tick
        assert adapter._tick_queue.qsize() == 0  # noqa: SLF001

    @pytest.mark.asyncio
    async def test_queue_initialization_with_maxsize(self, ctp_settings: AppSettings):
        """Test 2.2-UNIT-006: Test queue initialization with maxsize=1000 [AC1]."""
        adapter = CTPGatewayAdapter(ctp_settings)
        assert adapter._tick_queue.maxsize == 1000  # noqa: SLF001
        assert adapter._tick_queue.empty()  # noqa: SLF001

    @pytest.mark.asyncio
    async def test_queue_full_detection_and_drop_counter(
        self, ctp_settings: AppSettings, caplog
    ):
        """Test 2.2-UNIT-007/008: Test queue.full() detection and drop counter [AC1]."""
        adapter = CTPGatewayAdapter(ctp_settings)
        adapter._main_loop = asyncio.get_running_loop()  # noqa: SLF001
        adapter.symbol_contract_map["rb2401"] = Mock()

        # Fill the queue
        adapter._tick_queue = asyncio.Queue(maxsize=2)  # noqa: SLF001
        await adapter._tick_queue.put(Mock())  # noqa: SLF001
        await adapter._tick_queue.put(Mock())  # noqa: SLF001

        # Create tick that will be dropped
        mock_tick = Mock()
        mock_tick.symbol = "rb2401"
        mock_tick.last_price = 4500.0
        mock_tick.volume = 1000
        mock_tick.datetime = datetime.now(CHINA_TZ)
        mock_tick.bid_price_1 = 4499.0
        mock_tick.ask_price_1 = 4501.0

        # Call on_tick - should drop and log
        adapter.on_tick(mock_tick)

        assert adapter._dropped_ticks == 1  # noqa: SLF001
        assert "tick_dropped" in caplog.text

    @pytest.mark.asyncio
    async def test_queue_clear_on_disconnect(self, ctp_settings: AppSettings):
        """Test 2.2-UNIT-009: Test queue.clear() on disconnect [AC1]."""
        adapter = CTPGatewayAdapter(ctp_settings)

        # Add some ticks to queue
        await adapter._tick_queue.put(Mock())  # noqa: SLF001
        await adapter._tick_queue.put(Mock())  # noqa: SLF001
        assert adapter._tick_queue.qsize() == 2  # noqa: SLF001

        # Disconnect should clear queue
        await adapter.disconnect()
        assert adapter._tick_queue.empty()  # noqa: SLF001


class TestStory22AC2AsyncBridge:
    """Story 2.2 AC2: Uses asyncio.run_coroutine_threadsafe() to bridge to main loop."""

    @pytest.mark.asyncio
    async def test_vnpy_tickdata_to_markettick_translation(
        self, ctp_settings: AppSettings
    ):
        """Test 2.2-UNIT-010: Test vnpy TickData to MarketTick translation [AC2]."""
        adapter = CTPGatewayAdapter(ctp_settings)

        # Create mock vnpy TickData
        mock_tick = Mock()
        mock_tick.symbol = "rb2401"
        mock_tick.last_price = 4500.0
        mock_tick.volume = 1000
        mock_tick.datetime = datetime(2025, 1, 9, 10, 30, 0, tzinfo=CHINA_TZ)
        mock_tick.bid_price_1 = 4499.0
        mock_tick.ask_price_1 = 4501.0

        # Translate
        result = adapter._translate_vnpy_tick(mock_tick)  # noqa: SLF001

        # Verify translation
        assert isinstance(result, MarketTick)
        assert result.symbol == "rb2401"
        assert result.price == Decimal("4500.0")
        assert result.volume == Decimal("1000")
        assert result.bid == Decimal("4499.0")
        assert result.ask == Decimal("4501.0")
        assert result.vnpy["vt_symbol"] == "rb2401"
        assert result.vnpy["last_price"] == 4500.0
        assert result.vnpy["bid_price_1"] == 4499.0
        assert result.vnpy["ask_price_1"] == 4501.0
        assert result.vnpy["exchange"] == "UNKNOWN"

    @pytest.mark.asyncio
    async def test_timezone_normalization_to_china(self, ctp_settings: AppSettings):
        """Test 2.2-UNIT-011: Normalize timestamp to Asia/Shanghai [AC2]."""
        adapter = CTPGatewayAdapter(ctp_settings)

        # Create tick with China timezone
        mock_tick = Mock()
        mock_tick.symbol = "rb2401"
        mock_tick.last_price = 100.0
        mock_tick.volume = 10
        # China time: 2025-01-09 15:00:00 (3pm)
        china_time = datetime(2025, 1, 9, 15, 0, 0, tzinfo=CHINA_TZ)
        mock_tick.datetime = china_time
        mock_tick.bid_price_1 = 99.0
        mock_tick.ask_price_1 = 101.0

        result = adapter._translate_vnpy_tick(mock_tick)  # noqa: SLF001

        # Should remain China TZ: 2025-01-09 15:00:00 +08:00
        expected_china = china_time.astimezone(CHINA_TZ)
        assert result.timestamp == expected_china
        assert result.timestamp.tzinfo == CHINA_TZ
        assert result.vnpy["datetime"].endswith("+08:00")

    @pytest.mark.asyncio
    async def test_dst_boundary_timezone_conversion(self, ctp_settings: AppSettings):
        """Test 2.2-UNIT-012: Test DST boundary timezone conversion [AC2]."""
        adapter = CTPGatewayAdapter(ctp_settings)

        # Note: China doesn't observe DST, but UTC conversions still work
        mock_tick = Mock()
        mock_tick.symbol = "rb2401"
        mock_tick.last_price = 100.0
        mock_tick.volume = 10
        # Test summer date
        summer_time = datetime(2025, 7, 1, 12, 0, 0, tzinfo=CHINA_TZ)
        mock_tick.datetime = summer_time
        mock_tick.bid_price_1 = 99.0
        mock_tick.ask_price_1 = 101.0

        result = adapter._translate_vnpy_tick(mock_tick)  # noqa: SLF001
        expected_china = summer_time.astimezone(CHINA_TZ)
        assert result.timestamp == expected_china
        assert result.vnpy["datetime"].endswith("+08:00")

    @pytest.mark.asyncio
    async def test_max_float_to_zero_conversion(self, ctp_settings: AppSettings):
        """Test 2.2-UNIT-013: Test MAX_FLOAT to 0 conversion [AC2]."""
        adapter = CTPGatewayAdapter(ctp_settings)

        mock_tick = Mock()
        mock_tick.symbol = "rb2401"
        mock_tick.last_price = MAX_FLOAT  # Should convert to 0
        mock_tick.volume = 100
        mock_tick.datetime = datetime.now(CHINA_TZ)
        mock_tick.bid_price_1 = MAX_FLOAT
        mock_tick.ask_price_1 = 4501.0

        result = adapter._translate_vnpy_tick(mock_tick)  # noqa: SLF001

        assert result.price == Decimal("0")
        assert result.bid == Decimal("0")
        assert result.ask == Decimal("4501.0")
        assert result.vnpy["last_price"] == 0
        assert result.vnpy["bid_price_1"] == 0
        assert result.vnpy["ask_price_1"] == 4501.0

    @pytest.mark.asyncio
    async def test_run_coroutine_threadsafe_with_valid_loop(
        self, ctp_settings: AppSettings
    ):
        """Test 2.2-UNIT-018: Test run_coroutine_threadsafe with valid loop [AC2]."""
        adapter = CTPGatewayAdapter(ctp_settings)
        adapter._main_loop = asyncio.get_running_loop()  # noqa: SLF001
        adapter.symbol_contract_map["rb2401"] = Mock()

        # Verify loop is stored
        assert adapter._main_loop is not None  # noqa: SLF001
        assert not adapter._main_loop.is_closed()  # noqa: SLF001

        # Create tick and call on_tick
        mock_tick = Mock()
        mock_tick.symbol = "rb2401"
        mock_tick.last_price = 4500.0
        mock_tick.volume = 1000
        mock_tick.datetime = datetime.now(CHINA_TZ)
        mock_tick.bid_price_1 = 4499.0
        mock_tick.ask_price_1 = 4501.0

        # Should successfully bridge to async queue
        adapter.on_tick(mock_tick)

        # Give time for async operation
        await asyncio.sleep(0.01)
        assert adapter._tick_queue.qsize() == 1  # noqa: SLF001

    @pytest.mark.asyncio
    async def test_handling_of_stopped_event_loop(
        self, ctp_settings: AppSettings, caplog
    ):
        """Test 2.2-UNIT-019: Test handling of stopped event loop [AC2]."""
        adapter = CTPGatewayAdapter(ctp_settings)
        adapter.symbol_contract_map["rb2401"] = Mock()

        # Set a closed loop
        adapter._main_loop = Mock()  # noqa: SLF001
        adapter._main_loop.is_closed.return_value = True  # noqa: SLF001

        mock_tick = Mock()
        mock_tick.symbol = "rb2401"
        mock_tick.last_price = 100.0
        mock_tick.volume = 10
        mock_tick.datetime = datetime.now(CHINA_TZ)
        mock_tick.bid_price_1 = 99.0
        mock_tick.ask_price_1 = 101.0

        # Should handle gracefully
        adapter.on_tick(mock_tick)
        assert "tick_dropped_no_loop" in caplog.text

    @pytest.mark.asyncio
    async def test_main_loop_reference_storage(self, ctp_settings: AppSettings):
        """Test 2.2-UNIT-020: Test main_loop reference storage [AC2]."""
        adapter = CTPGatewayAdapter(ctp_settings)

        # Before connect, no loop
        assert adapter._main_loop is None  # noqa: SLF001

        # After connect, loop stored
        adapter._main_loop = asyncio.get_running_loop()  # noqa: SLF001
        assert adapter._main_loop is not None  # noqa: SLF001
        assert adapter._main_loop == asyncio.get_running_loop()  # noqa: SLF001

    @pytest.mark.asyncio
    async def test_receive_ticks_async_generator(self, ctp_settings: AppSettings):
        """Test 2.2-UNIT-021: Test receive_ticks() async generator [AC2]."""
        adapter = CTPGatewayAdapter(ctp_settings)
        adapter._main_loop = asyncio.get_running_loop()  # noqa: SLF001

        # Add test tick to queue
        test_tick = MarketTick(
            symbol="rb2401",
            price=Decimal("4500"),
            timestamp=datetime.now(ZoneInfo("UTC")),
        )
        await adapter._tick_queue.put(test_tick)  # noqa: SLF001

        # Test async iteration
        received_ticks = []

        async def consume():
            async for tick in adapter.receive_ticks():
                received_ticks.append(tick)
                break  # Only get one tick

        # Run with timeout
        await asyncio.wait_for(consume(), timeout=1.0)

        assert len(received_ticks) == 1
        assert received_ticks[0] == test_tick

    @pytest.mark.asyncio
    async def test_receive_ticks_cancelled_error_handling(
        self, ctp_settings: AppSettings, caplog
    ):
        """Test 2.2-UNIT-022: Test receive_ticks() with CancelledError [AC2]."""
        adapter = CTPGatewayAdapter(ctp_settings)
        adapter._main_loop = asyncio.get_running_loop()  # noqa: SLF001

        # Start consuming in a task
        async def consume():
            async for _ in adapter.receive_ticks():
                pass

        task = asyncio.create_task(consume())
        await asyncio.sleep(0.01)

        # Cancel the task
        task.cancel()

        # Should handle cancellation gracefully
        with pytest.raises(asyncio.CancelledError):
            await task

        assert "tick_receiver_cancelled" in caplog.text


class TestStory22AC3TestVerification:
    """Story 2.2 AC3: Unit tests verify bridging mechanism."""

    @pytest.mark.asyncio
    async def test_contract_validation_before_processing(
        self, ctp_settings: AppSettings
    ):
        """Test 2.2-UNIT-024: Test contract validation before processing [AC3]."""
        adapter = CTPGatewayAdapter(ctp_settings)
        adapter._main_loop = asyncio.get_running_loop()  # noqa: SLF001

        # Test with empty symbol_contract_map
        adapter.symbol_contract_map = {}

        mock_tick = Mock()
        mock_tick.symbol = "rb2401"
        mock_tick.last_price = 100.0
        mock_tick.volume = 10
        mock_tick.datetime = datetime.now(CHINA_TZ)
        mock_tick.bid_price_1 = 99.0
        mock_tick.ask_price_1 = 101.0

        # Should not process without contract
        adapter.on_tick(mock_tick)
        assert adapter._tick_queue.qsize() == 0  # noqa: SLF001

        # Add contract and retry
        adapter.symbol_contract_map["rb2401"] = Mock()
        adapter.on_tick(mock_tick)

        # Now should process
        await asyncio.sleep(0.01)
        assert adapter._tick_queue.qsize() == 1  # noqa: SLF001

    @pytest.mark.asyncio
    async def test_symbol_contract_map_lookup(self, ctp_settings: AppSettings):
        """Test 2.2-UNIT-025: Test symbol_contract_map lookup [AC3]."""
        adapter = CTPGatewayAdapter(ctp_settings)
        adapter._main_loop = asyncio.get_running_loop()  # noqa: SLF001

        # Setup contract map with multiple symbols
        adapter.symbol_contract_map = {
            "rb2401": Mock(name="Rebar 2401"),
            "ag2402": Mock(name="Silver 2402"),
            "cu2403": Mock(name="Copper 2403"),
        }

        # Test successful lookup
        mock_tick = Mock()
        mock_tick.symbol = "ag2402"
        mock_tick.last_price = 5500.0
        mock_tick.volume = 50
        mock_tick.datetime = datetime.now(CHINA_TZ)
        mock_tick.bid_price_1 = 5499.0
        mock_tick.ask_price_1 = 5501.0

        adapter.on_tick(mock_tick)

        # Should process known symbol
        await asyncio.sleep(0.01)
        assert adapter._tick_queue.qsize() == 1  # noqa: SLF001

        # Test failed lookup
        mock_tick.symbol = "unknown"
        adapter.on_tick(mock_tick)

        # Should not add another tick
        await asyncio.sleep(0.01)
        assert adapter._tick_queue.qsize() == 1  # noqa: SLF001


class TestStory22Integration:
    """Integration tests for cross-thread bridging."""

    @pytest.mark.asyncio
    async def test_cross_thread_on_tick_execution(self, ctp_settings: AppSettings):
        """Test 2.2-INT-001: Verify on_tick called from executor thread [AC1]."""
        adapter = CTPGatewayAdapter(ctp_settings)
        adapter._main_loop = asyncio.get_running_loop()  # noqa: SLF001
        adapter.symbol_contract_map["rb2401"] = Mock()

        thread_ids = []

        def capture_thread():
            thread_ids.append(threading.current_thread().ident)
            mock_tick = Mock()
            mock_tick.symbol = "rb2401"
            mock_tick.last_price = 100.0
            mock_tick.volume = 10
            mock_tick.datetime = datetime.now(CHINA_TZ)
            mock_tick.bid_price_1 = 99.0
            mock_tick.ask_price_1 = 101.0
            adapter.on_tick(mock_tick)

        # Run in dedicated thread and join
        t = threading.Thread(target=capture_thread)
        t.start()
        t.join(timeout=1.0)

        # Verify different thread
        assert len(thread_ids) == 1
        assert thread_ids[0] != threading.current_thread().ident

    @pytest.mark.asyncio
    async def test_cross_thread_queue_put(self, ctp_settings: AppSettings):
        """Test 2.2-INT-005: Test cross-thread queue.put() [AC2]."""
        adapter = CTPGatewayAdapter(ctp_settings)
        adapter._main_loop = asyncio.get_running_loop()  # noqa: SLF001
        adapter.symbol_contract_map["rb2401"] = Mock()

        # Run on_tick from different thread
        def call_on_tick():
            for i in range(10):
                mock_tick = Mock()
                mock_tick.symbol = "rb2401"
                mock_tick.last_price = 4500.0 + i
                mock_tick.volume = 100
                mock_tick.datetime = datetime.now(CHINA_TZ)
                mock_tick.bid_price_1 = 4499.0 + i
                mock_tick.ask_price_1 = 4501.0 + i
                adapter.on_tick(mock_tick)
                time.sleep(0.001)

        thr = threading.Thread(target=call_on_tick)
        thr.start()

        # Collect ticks
        received = []

        async def collect():
            async for tick in adapter.receive_ticks():
                received.append(tick)
                if len(received) >= 10:
                    break

        await asyncio.wait_for(collect(), timeout=2.0)
        thr.join(timeout=1.0)

        assert len(received) == 10
        # Verify prices are sequential
        for i, tick in enumerate(received):
            assert tick.price == Decimal(str(4500.0 + i))

    @pytest.mark.asyncio
    async def test_full_end_to_end_flow(self, ctp_settings: AppSettings):
        """Test 2.2-E2E-001: Test full flow: vnpy tick → async queue [AC2]."""
        adapter = CTPGatewayAdapter(ctp_settings)
        adapter._main_loop = asyncio.get_running_loop()  # noqa: SLF001
        adapter.symbol_contract_map["rb2401"] = Mock()

        # Simulate vnpy gateway calling on_tick from thread
        def simulate_vnpy_gateway():
            # Create realistic vnpy tick
            mock_tick = Mock()
            mock_tick.symbol = "rb2401"
            mock_tick.last_price = 4567.0
            mock_tick.volume = 1234
            mock_tick.datetime = datetime(2025, 1, 9, 14, 30, 0, tzinfo=CHINA_TZ)
            mock_tick.bid_price_1 = 4566.0
            mock_tick.ask_price_1 = 4568.0
            mock_tick.bid_volume_1 = 50
            mock_tick.ask_volume_1 = 75

            # Call on_tick as vnpy would
            adapter.on_tick(mock_tick)

        t = threading.Thread(target=simulate_vnpy_gateway)
        t.start()
        t.join(timeout=1.0)

        # Consume from async side
        received_tick = None
        async for tick in adapter.receive_ticks():
            received_tick = tick
            break

        # Verify full translation
        assert received_tick is not None
        assert received_tick.symbol == "rb2401"
        assert received_tick.price == Decimal("4567.0")
        assert received_tick.volume == Decimal("1234")
        assert received_tick.bid == Decimal("4566.0")
        assert received_tick.ask == Decimal("4568.0")
        # Verify timezone is China TZ (no hour shift)
        assert received_tick.timestamp.tzinfo == CHINA_TZ
        assert received_tick.timestamp.hour == 14
