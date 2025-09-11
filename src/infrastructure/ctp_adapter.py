# IMPORTANT: CTP retries must spawn a NEW session thread after failure/disconnect.
"""CTP Gateway Adapter implementing the MarketDataPort.

Runs a blocking vnpy CTP gateway loop inside a supervised worker thread
with exponential backoff and capped retries. Per CTP best practice, a
fresh session thread is spawned on each retry after failure/disconnect.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from decimal import Decimal
import logging
import sys
import threading
import time
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from src.domain.ports import MarketDataPort

if TYPE_CHECKING:  # avoid runtime import for typing only
    from collections.abc import AsyncIterator, Callable

    from src.config import AppSettings
    from src.domain.models import MarketDataSubscription, MarketTick

logger = logging.getLogger(__name__)

# Constants for vnpy compatibility
MAX_FLOAT = sys.float_info.max
CHINA_TZ = ZoneInfo("Asia/Shanghai")

# Exchange mapping from CTP to vnpy Exchange enum strings
EXCHANGE_CTP2VT = {
    "CFFEX": "CFFEX",
    "SHFE": "SHFE",
    "CZCE": "CZCE",
    "DCE": "DCE",
    "INE": "INE",
    "GFEX": "GFEX",
}


@dataclass(frozen=True)
class RetryPolicy:
    base_backoff: float = 0.5
    multiplier: float = 2.0
    max_backoff: float = 2.0
    max_retries: int = 3


def normalize_address(addr: str) -> str:
    """Normalize address to include tcp:// or ssl:// prefix when missing."""
    if addr.startswith(("tcp://", "ssl://")):
        return addr
    return f"tcp://{addr}"


class CTPGatewayAdapter(MarketDataPort):
    """Adapter that manages the vnpy CTP gateway lifecycle in a worker thread."""

    def __init__(
        self,
        settings: AppSettings,
        gateway_connect: (
            Callable[[dict[str, Any], Callable[[], bool]], None] | None
        ) = None,
        *,
        retry_policy: RetryPolicy | None = None,
        executor: ThreadPoolExecutor | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        """Initialize adapter with settings and injectable hooks for testability."""
        self.settings = settings
        self.retry_policy = retry_policy or RetryPolicy()
        # Lazily create executor to avoid lingering threads in unit tests
        self.executor: ThreadPoolExecutor | None = executor
        self._owns_executor = executor is None
        self._shutdown = threading.Event()
        self._future: Future[None] | None = None
        self._sleep = sleep_fn
        # gateway_connect(setting, should_shutdown) should run the blocking loop or raise on failure
        self._gateway_connect = gateway_connect or self._default_gateway_connect
        self._session_counter = 0

        # Story 2.2: Async bridge components
        self._tick_queue: asyncio.Queue[MarketTick] = asyncio.Queue(maxsize=1000)
        self._main_loop: asyncio.AbstractEventLoop | None = None
        self._dropped_ticks = 0
        self.symbol_contract_map: dict[str, Any] = (
            {}
        )  # Will be populated by vnpy gateway
        # Story 2.4.2: subscription state
        self._subs_by_id: dict[str, MarketDataSubscription] = {}
        self._sub_id_by_symbol: dict[str, str] = {}
        self._sub_seq = 0

    async def connect(self) -> None:
        """Start the supervised worker thread."""
        # Store main loop reference for thread-safe bridging
        self._main_loop = asyncio.get_running_loop()
        self._shutdown.clear()
        # Create executor on demand
        if self.executor is None:
            self.executor = ThreadPoolExecutor(
                max_workers=2, thread_name_prefix="ctp-gw"
            )
            self._owns_executor = True
        if self._future is None or getattr(self._future, "done", lambda: True)():
            self._future = self.executor.submit(self._supervisor)

    async def disconnect(self) -> None:
        """Signal shutdown and wait for the worker to exit."""
        self._shutdown.set()
        # Clear queue on disconnect
        while not self._tick_queue.empty():
            try:
                self._tick_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        deadline = time.time() + 5.0
        while self._future is not None and not self._future.done():
            if time.time() >= deadline:
                break
            await self._async_sleep(0.02)
        # Shutdown owned executor to prevent atexit join
        if self._owns_executor and self.executor is not None:
            try:
                self.executor.shutdown(wait=False, cancel_futures=True)
            except Exception:  # noqa: BLE001
                logger.warning("executor_shutdown_error", exc_info=True)
            finally:
                self.executor = None
                self._owns_executor = False

    async def subscribe(self, symbol: str) -> MarketDataSubscription:
        """Subscribe to a symbol; idempotent for the same symbol key.

        - Generates unique subscription_id on first subscribe.
        - Maintains bidirectional mappings for lookup.
        - Prepares live hook (no-op for 2.4.2; wired in 2.4.3).
        """
        norm_symbol = (symbol or "").strip()
        if "." in norm_symbol:
            base_symbol, exchange = norm_symbol.rsplit(".", 1)
        else:
            base_symbol, exchange = norm_symbol, "UNKNOWN"

        symbol_key = f"{base_symbol}.{exchange}"

        # Idempotent behavior: return existing subscription for same symbol key
        existing_id = self._sub_id_by_symbol.get(symbol_key)
        if existing_id is not None:
            sub = self._subs_by_id[existing_id]
            logger.info(
                "duplicate_subscription",
                extra={
                    "symbol": base_symbol,
                    "exchange": exchange,
                    "id": sub.subscription_id,
                },
            )
            return sub

        # Generate a unique subscription id
        self._sub_seq += 1
        sub_id = f"sub-{self._sub_seq}"

        # Pydantic will validate symbol format via model
        from src.domain.models import MarketDataSubscription

        sub = MarketDataSubscription(
            subscription_id=sub_id, symbol=base_symbol, exchange=exchange
        )

        # Record mappings
        self._subs_by_id[sub_id] = sub
        self._sub_id_by_symbol[symbol_key] = sub_id

        # Live hook placeholder (no-op for now)
        try:
            await self._subscribe_live_hook(base_symbol, exchange)
        except Exception:  # noqa: BLE001
            logger.warning(
                "live_subscribe_hook_error",
                exc_info=True,
                extra={"symbol": base_symbol, "exchange": exchange},
            )

        logger.info(
            "subscribed",
            extra={"id": sub_id, "symbol": base_symbol, "exchange": exchange},
        )
        return sub

    async def unsubscribe(self, subscription_id: str) -> None:
        """Unsubscribe by ID; idempotent for unknown IDs.

        Unknown IDs log a warning and return without error.
        """
        sub = self._subs_by_id.get(subscription_id)
        if sub is None:
            logger.warning("unknown_subscription_id", extra={"id": subscription_id})
            return

        symbol_key = f"{sub.symbol}.{sub.exchange}"
        # Live hook placeholder (no-op for now)
        try:
            await self._unsubscribe_live_hook(sub.symbol, sub.exchange)
        except Exception:  # noqa: BLE001
            logger.warning(
                "live_unsubscribe_hook_error",
                exc_info=True,
                extra={"symbol": sub.symbol, "exchange": sub.exchange},
            )

        # Remove mappings
        self._subs_by_id.pop(subscription_id, None)
        self._sub_id_by_symbol.pop(symbol_key, None)
        logger.info("unsubscribed", extra={"id": subscription_id})

    async def receive_ticks(self) -> AsyncIterator[MarketTick]:
        """Async generator yielding market ticks as they arrive."""
        try:
            while True:
                tick = await self._tick_queue.get()
                yield tick
        except asyncio.CancelledError:
            # Clean shutdown; log at WARNING so test harness captures it
            logger.warning("tick_receiver_cancelled")
            raise

    # Internal methods
    def _supervisor(self) -> None:
        """Run gateway with retry/backoff until success or max retries or shutdown.

        Spawn a new session thread per attempt as CTP APIs often require a fresh
        thread after failures/disconnects.
        """
        attempts = 0
        while not self._shutdown.is_set():
            setting = self._build_vnpy_setting()
            exc = self._run_session_thread(setting)
            if self._shutdown.is_set():
                return
            if exc is None:
                # Clean end of session (no exception)
                return

            # Failure path: compute backoff and retry with a NEW thread
            attempts += 1
            if attempts > self.retry_policy.max_retries:
                logger.error(
                    "ctp_gateway_connect_failed_max_retries",
                    extra={"attempt": attempts, "reason": str(exc)},
                )
                return
            backoff = min(
                self.retry_policy.base_backoff
                * (self.retry_policy.multiplier ** (attempts - 1)),
                self.retry_policy.max_backoff,
            )
            logger.warning(
                "ctp_gateway_retry",
                extra={
                    "attempt": attempts,
                    "reason": str(exc),
                    "next_backoff": round(backoff, 2),
                },
            )
            self._sleep(backoff)

    def _run_session_thread(self, setting: dict[str, Any]) -> Exception | None:
        """Start a fresh thread to run one gateway session and wait for termination.

        Returns exception if the session failed, else None.
        """
        exc_container: dict[str, Exception] = {}

        def should_shutdown() -> bool:
            return self._shutdown.is_set()

        def target() -> None:
            try:
                self._gateway_connect(setting, should_shutdown)
            except Exception as exc:  # noqa: BLE001
                exc_container["exc"] = exc

        self._session_counter += 1
        t = threading.Thread(
            target=target, name=f"ctp-session-{self._session_counter}", daemon=True
        )
        t.start()
        t.join()
        return exc_container.get("exc")

    def _build_vnpy_setting(self) -> dict[str, Any]:
        """Build vnpy CTP gateway setting dict with expected Chinese keys."""
        return {
            "用户名": self.settings.ctp_user_id,
            "密码": self.settings.ctp_password,
            "经纪商代码": self.settings.ctp_broker_id,
            "交易服务器": normalize_address(self.settings.ctp_td_address or ""),
            "行情服务器": normalize_address(self.settings.ctp_md_address or ""),
            "产品名称": self.settings.ctp_app_id,
            "授权编码": self.settings.ctp_auth_code,
        }

    def _default_gateway_connect(
        self, _setting: dict[str, Any], should_shutdown: Callable[[], bool]
    ) -> None:
        """Provide vnpy gateway loop placeholder; cooperate with shutdown."""
        while not should_shutdown():
            time.sleep(0.05)

    def on_tick(self, tick: Any) -> None:
        """Override from vnpy BaseGateway - called when market data arrives.

        Args:
            tick: vnpy TickData object with market data

        """
        # Check if contract data is available
        if not hasattr(tick, "symbol") or tick.symbol not in self.symbol_contract_map:
            return  # Ignore until contracts loaded

        # Translate vnpy tick to domain model
        try:
            domain_tick = self._translate_vnpy_tick(tick)
        except Exception as e:
            logger.exception(
                "tick_translation_error",
                extra={"error": str(e), "symbol": getattr(tick, "symbol", "unknown")},
            )
            return

        # Bridge to async queue if not full
        if not self._tick_queue.full():
            if self._main_loop and not self._main_loop.is_closed():
                try:
                    asyncio.run_coroutine_threadsafe(
                        self._tick_queue.put(domain_tick), self._main_loop
                    )
                    # We don't wait for the future to complete (fire-and-forget)
                except Exception as e:
                    logger.exception("tick_bridge_error", extra={"error": str(e)})
            else:
                logger.warning("tick_dropped_no_loop")
        else:
            self._dropped_ticks += 1
            logger.warning(
                "tick_dropped",
                extra={"count": self._dropped_ticks, "symbol": domain_tick.symbol},
            )

    def _translate_vnpy_tick(self, vnpy_tick: Any) -> MarketTick:
        """Translate vnpy TickData to domain MarketTick.

        Args:
            vnpy_tick: vnpy TickData object

        Returns:
            Domain MarketTick model

        """
        from src.domain.models import MarketTick

        # Handle timezone normalization to China timezone
        tick_datetime = vnpy_tick.datetime
        if tick_datetime.tzinfo is None:
            # Assume China timezone if not specified
            tick_datetime = tick_datetime.replace(tzinfo=CHINA_TZ)
        elif tick_datetime.tzinfo != CHINA_TZ:
            # Convert to China timezone if different
            tick_datetime = tick_datetime.astimezone(CHINA_TZ)

        # Keep timestamp in China timezone (project-wide convention)
        china_datetime = tick_datetime

        # Handle MAX_FLOAT adjustment for prices
        def adjust_price(price: float) -> Decimal:
            if price == MAX_FLOAT or price >= MAX_FLOAT:
                return Decimal(0)
            return Decimal(str(price))

        # Map core fields
        return MarketTick(
            symbol=vnpy_tick.symbol,
            price=adjust_price(vnpy_tick.last_price),
            volume=Decimal(str(vnpy_tick.volume)) if vnpy_tick.volume else None,
            timestamp=china_datetime,
            bid=(
                adjust_price(getattr(vnpy_tick, "bid_price_1", 0))
                if getattr(vnpy_tick, "bid_price_1", None) is not None
                else None
            ),
            ask=(
                adjust_price(getattr(vnpy_tick, "ask_price_1", 0))
                if getattr(vnpy_tick, "ask_price_1", None) is not None
                else None
            ),
        )

    async def _async_sleep(self, seconds: float) -> None:
        import asyncio as _asyncio

        await _asyncio.sleep(seconds)

    # ---- Live connector hook placeholders (wired in Story 2.4.3) ----
    async def _subscribe_live_hook(self, _symbol: str, _exchange: str) -> None:
        return None

    async def _unsubscribe_live_hook(self, _symbol: str, _exchange: str) -> None:
        return None
