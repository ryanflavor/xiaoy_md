"""Lightweight NATS RPC server for control plane endpoints.

Exposes request/response handlers:
- md.contracts.list → returns available vt_symbols and source
- md.subscribe.bulk → performs bulk subscription via MarketDataService

This module uses a dedicated NATS connection. It relies on injected
collaborators (service/adapter) without importing from application layer
to preserve Hexagonal Architecture boundaries.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import datetime
import json
import logging
from typing import Any
from zoneinfo import ZoneInfo

from nats.aio.client import Client as NATSClient

logger = logging.getLogger(__name__)
CHINA_TZ = ZoneInfo("Asia/Shanghai")


@dataclass
class _RpcSubscription:
    subject: str
    cb: Any


class NATSRPCServer:
    """NATS-based RPC server for control plane endpoints."""

    CONTRACTS_LIST_SUBJECT = "md.contracts.list"
    SUBSCRIBE_BULK_SUBJECT = "md.subscribe.bulk"

    def __init__(self, settings: Any, service: Any, adapter: Any | None) -> None:
        """Create RPC server with collaborators.

        Args:
            settings: Configuration providing NATS URL and client id
            service: Object exposing `subscribe_to_symbol(str)` coroutine
            adapter: Adapter exposing optional `update_contracts(list[str])` coroutine

        """
        self._settings = settings
        self._service = service
        self._adapter = adapter
        self._nc: NATSClient | None = None
        self._subscriptions: list[_RpcSubscription] = []

    async def start(self) -> None:
        """Connect to NATS and register RPC handlers."""
        if self._nc is not None:
            return
        self._nc = NATSClient()
        await self._nc.connect(
            servers=[self._settings.nats_url],
            name=f"{self._settings.nats_client_id}-rpc",
        )

        # Register handlers
        async def _contracts_handler(msg: Any) -> None:
            payload = await self._handle_contracts_list(msg.data)
            await msg.respond(json.dumps(payload).encode())

        sub1 = await self._nc.subscribe(
            self.CONTRACTS_LIST_SUBJECT, cb=_contracts_handler
        )
        self._subscriptions.append(_RpcSubscription(self.CONTRACTS_LIST_SUBJECT, sub1))

        async def _bulk_handler(msg: Any) -> None:
            payload = await self._handle_subscribe_bulk(msg.data)
            await msg.respond(json.dumps(payload).encode())

        sub2 = await self._nc.subscribe(self.SUBSCRIBE_BULK_SUBJECT, cb=_bulk_handler)
        self._subscriptions.append(_RpcSubscription(self.SUBSCRIBE_BULK_SUBJECT, sub2))

        logger.info(
            "rpc_listeners_ready",
            extra={"subjects": [s.subject for s in self._subscriptions]},
        )

    async def stop(self) -> None:
        """Unsubscribe and close the NATS connection."""
        if not self._nc:
            return
        try:
            for entry in self._subscriptions:
                try:
                    await entry.cb.unsubscribe()  # nats subscription object
                except Exception:  # noqa: BLE001
                    logger.debug(
                        "rpc_unsubscribe_error",
                        exc_info=True,
                        extra={"subject": entry.subject},
                    )
        finally:
            self._subscriptions.clear()
            try:
                await asyncio.wait_for(self._nc.drain(), timeout=0.5)
            except Exception as e:  # noqa: BLE001
                try:
                    await self._nc.close()
                except Exception as ce:  # noqa: BLE001
                    logger.debug(
                        "rpc_close_error_after_drain",
                        exc_info=True,
                        extra={"error": str(ce), "before": str(e)},
                    )
            else:
                try:
                    await self._nc.close()
                except Exception as e:  # noqa: BLE001
                    logger.debug(
                        "rpc_close_error", exc_info=True, extra={"error": str(e)}
                    )
            self._nc = None

    async def _handle_contracts_list(self, _data: bytes) -> dict[str, Any]:
        """Handle md.contracts.list requests."""
        # Prefer cached vt_symbols from adapter when available
        vt_symbols: list[str] = []
        source = "empty"
        ts = datetime.now(CHINA_TZ).isoformat()

        try:
            if self._adapter is not None:
                vt_symbols = sorted(getattr(self._adapter, "_contracts_vt", set()))
        except Exception:  # noqa: BLE001
            vt_symbols = []

        if vt_symbols:
            source = "cache"
            return {"symbols": vt_symbols, "source": source, "ts": ts}

        # Attempt live query via connector if available
        try:
            from src.infrastructure import ctp_live_connector as live

            if hasattr(live, "query_all_contracts"):
                result: list[str] = await _maybe_await(live.query_all_contracts(1.0))
            else:
                result = []
        except Exception:  # noqa: BLE001
            result = []

        if result:
            vt_syms = [str(x) for x in result]
            try:
                if self._adapter is not None and hasattr(
                    self._adapter, "update_contracts"
                ):
                    await _maybe_await(self._adapter.update_contracts(vt_syms))
            except Exception:  # noqa: BLE001
                logger.debug("update_contracts_failed", exc_info=True)
            source = "vnpy"
            vt_symbols = sorted(vt_syms)

        return {"symbols": vt_symbols, "source": source, "ts": ts}

    async def _handle_subscribe_bulk(self, data: bytes) -> dict[str, Any]:
        """Handle md.subscribe.bulk requests."""
        try:
            payload = json.loads(data.decode() or "{}")
        except Exception:  # noqa: BLE001
            payload = {}
        symbols = payload.get("symbols") or []
        if not isinstance(symbols, list):
            symbols = []

        accepted: list[str] = []
        rejected: list[dict[str, str]] = []
        seen: set[str] = set()

        for vt_symbol in symbols:
            s = str(vt_symbol)
            if s in seen:
                continue
            seen.add(s)
            try:
                # Delegate to injected service; errors flow through and are recorded
                await self._service.subscribe_to_symbol(s)
            except Exception as e:  # noqa: BLE001
                rejected.append({"symbol": s, "reason": str(e)})
            else:
                accepted.append(s)

        ts = datetime.now(CHINA_TZ).isoformat()
        return {"accepted": accepted, "rejected": rejected, "ts": ts}


async def _maybe_await(value: Any) -> Any:
    """Await value if it's awaitable; otherwise return it directly."""
    if isinstance(value, Awaitable):
        return await value
    return value
