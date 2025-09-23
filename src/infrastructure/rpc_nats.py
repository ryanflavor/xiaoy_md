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
from pydantic import SecretStr


def _resolve_secret(value: str | SecretStr | None) -> str | None:
    if isinstance(value, SecretStr):
        return value.get_secret_value()
    return value


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
    SUBSCRIPTIONS_ACTIVE_SUBJECT = "md.subscriptions.active"

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
        options: dict[str, Any] = {
            "servers": [self._settings.nats_url],
            "name": f"{self._settings.nats_client_id}-rpc",
        }
        user = getattr(self._settings, "nats_user", None)
        pwd = _resolve_secret(getattr(self._settings, "nats_password", None))
        if user and pwd:
            options["user"] = user
            options["password"] = pwd
        await self._nc.connect(**options)

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

        async def _active_handler(msg: Any) -> None:
            payload = await self._handle_active_subscriptions(msg.data)
            await msg.respond(json.dumps(payload).encode())

        sub3 = await self._nc.subscribe(
            self.SUBSCRIPTIONS_ACTIVE_SUBJECT, cb=_active_handler
        )
        self._subscriptions.append(
            _RpcSubscription(self.SUBSCRIPTIONS_ACTIVE_SUBJECT, sub3)
        )

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

            # Parse optional timeout_s from request payload (defaults to 3.0s)
            timeout_s = 3.0
            try:
                req = json.loads(_data.decode() or "{}")
                t = float(req.get("timeout_s", timeout_s))
                # clamp to 0.5..15s
                t = max(t, 0.5)
                t = min(t, 15.0)
                timeout_s = t
            except Exception as e:  # noqa: BLE001
                logger.debug(
                    "contracts_list_parse_timeout_error",
                    exc_info=True,
                    extra={"error": str(e)},
                )

            if hasattr(live, "query_all_contracts"):
                result: list[str] = await _maybe_await(
                    live.query_all_contracts(timeout_s)
                )
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

    async def _handle_active_subscriptions(
        self, raw: bytes | None = None
    ) -> dict[str, Any]:
        """Handle md.subscriptions.active requests."""
        ts = datetime.now(CHINA_TZ).isoformat()

        limit = _parse_subscription_limit(raw)

        if not hasattr(self._service, "list_active_subscriptions"):
            logger.warning("active_subscriptions_not_supported")
            return {
                "subscriptions": [],
                "total": 0,
                "ts": ts,
                "source": "unsupported",
            }

        try:
            data = await self._service.list_active_subscriptions()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "active_subscriptions_error",
                exc_info=True,
                extra={"error": str(exc)},
            )
            return {
                "subscriptions": [],
                "total": 0,
                "ts": ts,
                "source": "error",
                "error": str(exc),
            }

        symbols = [_normalize_subscription_symbol(entry) for entry in data]
        symbols = [symbol for symbol in symbols if symbol]

        truncated = False
        if limit is not None and len(symbols) > limit:
            truncated = True
            symbols = symbols[:limit]

        payload: dict[str, Any] = {
            "subscriptions": symbols,
            "total": len(data),
            "ts": ts,
            "source": "market-data-service",
        }
        if truncated:
            payload["truncated"] = True
        return payload


def _parse_subscription_limit(raw: bytes | None) -> int | None:
    if not raw:
        return None
    try:
        req = json.loads(raw.decode() or "{}")
    except Exception:  # noqa: BLE001
        return None
    value = req.get("limit")
    try:
        candidate = int(value)
    except (TypeError, ValueError):
        return None
    return candidate if candidate > 0 else None


def _normalize_subscription_symbol(entry: Any) -> str | None:
    if isinstance(entry, dict):
        raw_symbol = entry.get("symbol") or entry.get("vt_symbol")
        if isinstance(raw_symbol, str):
            return raw_symbol.strip() or None
        if raw_symbol is not None:
            return str(raw_symbol).strip() or None
        return None
    if isinstance(entry, str):
        return entry.strip() or None
    if entry is not None:
        return str(entry).strip() or None
    return None


async def _maybe_await(value: Any) -> Any:
    """Await value if it's awaitable; otherwise return it directly."""
    if isinstance(value, Awaitable):
        return await value
    return value
