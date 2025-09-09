# IMPORTANT: CTP retries must spawn a NEW session thread after failure/disconnect.
"""CTP Gateway Adapter implementing the MarketDataPort.

Runs a blocking vnpy CTP gateway loop inside a supervised worker thread
with exponential backoff and capped retries. Per CTP best practice, a
fresh session thread is spawned on each retry after failure/disconnect.
"""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
import logging
import threading
import time
from typing import TYPE_CHECKING, Any

from src.domain.ports import MarketDataPort

if TYPE_CHECKING:  # avoid runtime import for typing only
    from collections.abc import AsyncIterator, Callable

    from src.config import AppSettings
    from src.domain.models import MarketDataSubscription, MarketTick

logger = logging.getLogger(__name__)


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
        self.executor = executor or ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="ctp-gw"
        )
        self._shutdown = threading.Event()
        self._future: Future[None] | None = None
        self._sleep = sleep_fn
        # gateway_connect(setting, should_shutdown) should run the blocking loop or raise on failure
        self._gateway_connect = gateway_connect or self._default_gateway_connect
        self._session_counter = 0

    async def connect(self) -> None:
        """Start the supervised worker thread."""
        self._shutdown.clear()
        if self._future is None or getattr(self._future, "done", lambda: True)():
            self._future = self.executor.submit(self._supervisor)

    async def disconnect(self) -> None:
        """Signal shutdown and wait for the worker to exit."""
        self._shutdown.set()
        deadline = time.time() + 5.0
        while self._future is not None and not self._future.done():
            if time.time() >= deadline:
                break
            await self._async_sleep(0.02)

    async def subscribe(self, symbol: str) -> MarketDataSubscription:
        raise NotImplementedError("subscribe() implemented in Story 2.2")

    async def unsubscribe(self, subscription_id: str) -> None:
        raise NotImplementedError("unsubscribe() implemented in Story 2.2")

    def receive_ticks(self) -> AsyncIterator[MarketTick]:
        raise NotImplementedError("receive_ticks() implemented in Story 2.2")

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

    async def _async_sleep(self, seconds: float) -> None:
        import asyncio as _asyncio

        await _asyncio.sleep(seconds)
