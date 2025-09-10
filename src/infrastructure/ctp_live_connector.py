"""vn.py-based live CTP connector tailored for the 2.2 bridge.

Provides `live_gateway_connect(setting, should_shutdown)` that:
- Connects to CTP via vn.py
- If `_on_tick` attribute is present on the function, forwards ticks to it
- Subscribes to `CTP_SYMBOL` from env
"""

from __future__ import annotations

import logging
import os
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # type-only imports
    from collections.abc import Callable


def set_on_tick(callback: Any) -> None:
    """Public API to set forwarding callback used by live_gateway_connect.

    Stores the callback on the function object to avoid extra globals.
    """
    name = "_on_tick"
    setattr(live_gateway_connect, name, callback)


def _connect_components(setting: dict[str, object]) -> tuple[Any, Any, Any]:
    """Create EventEngine, MainEngine, and CTP gateway; return (ee, me, gw)."""
    try:
        from vnpy.event import EventEngine  # type: ignore[import-untyped]
        from vnpy.trader.engine import MainEngine  # type: ignore[import-untyped]
        from vnpy_ctp import CtpGateway  # type: ignore[import-untyped]
    except Exception as exc:
        raise RuntimeError from exc

    ee = EventEngine()
    me = MainEngine(ee)
    me.add_gateway(CtpGateway)

    try:
        me.connect(setting, "CTP")
    except TypeError:
        me.connect("CTP", setting)

    gw: Any | None = None
    try:
        gw = me.get_gateway("CTP")
    except Exception:  # noqa: BLE001
        gw = getattr(me, "gateways", {}).get("CTP")
    if gw is None:
        raise LookupError
    return ee, me, gw


def _attach_forwarders(log: logging.Logger, ee: Any, gw: Any) -> None:
    """Attach tick forwarders via gateway.on_tick and EventEngine eTick if set."""
    cb = getattr(live_gateway_connect, "_on_tick", None)
    if cb is None:
        return

    def _forward_tick(tick: Any) -> None:
        try:
            cb(tick)
        except Exception:
            log.exception("bridge_on_tick_exception")

    # Approach 1: Override gateway on_tick directly
    try:
        gw.on_tick = _forward_tick
        log.info("bridge_on_tick_attached")
    except Exception:
        log.exception("bridge_attach_on_tick_failed")

    # Approach 2: Subscribe to EventEngine eTick events and forward
    try:

        def _on_event(evt: Any) -> None:
            try:
                cb(getattr(evt, "data", evt))
            except Exception:
                log.exception("bridge_on_tick_event_exception")

        ee.register("eTick", _on_event)
        log.info("bridge_event_on_tick_attached")
    except Exception:
        log.exception("bridge_event_on_tick_attach_failed")


def _subscribe_symbol(log: logging.Logger, ee: Any, me: Any, gw: Any) -> None:
    """Subscribe to vt_symbol from env with brief MD login wait."""
    vt = os.environ.get("CTP_SYMBOL")
    if not (vt and "." in vt):
        return

    md_ready = {"ok": False}
    try:

        def _on_log(evt: Any) -> None:
            msg = getattr(getattr(evt, "data", None), "msg", "")
            if isinstance(msg, str) and (
                "行情服务器登录成功" in msg or "行情服务器连接成功" in msg
            ):
                md_ready["ok"] = True

        ee.register("eLog", _on_log)
    except Exception:  # noqa: BLE001
        log.debug("bridge_log_listener_setup_skipped")

    deadline = time.time() + 5.0
    while not md_ready["ok"] and time.time() < deadline:
        time.sleep(0.1)

    from vnpy.trader.object import (  # type: ignore[import-untyped]
        Exchange,
        SubscribeRequest,
    )

    sym, ex = vt.split(".", 1)
    try:
        ex_enum: Any = Exchange(ex)
    except Exception:  # noqa: BLE001
        ex_enum = ex
    sub = SubscribeRequest(symbol=sym, exchange=ex_enum)
    try:
        me.subscribe(sub, "CTP")
        log.info("bridge_subscribed", extra={"vt_symbol": vt})
    except Exception:  # noqa: BLE001
        try:
            gw.subscribe(sub)
            log.info("bridge_subscribed_gw", extra={"vt_symbol": vt})
        except Exception:
            log.exception("bridge_subscribe_failed", extra={"vt_symbol": vt})


def live_gateway_connect(
    setting: dict[str, object], should_shutdown: Callable[[], bool]
) -> None:
    """Run vn.py session, attach forwarders, subscribe, and idle until shutdown."""
    log = logging.getLogger(__name__)
    ee, me, gw = _connect_components(setting)
    _attach_forwarders(log, ee, gw)
    _subscribe_symbol(log, ee, me, gw)

    # Idle loop until shutdown
    try:
        while not should_shutdown():
            time.sleep(0.1)
    finally:
        import contextlib

        with contextlib.suppress(Exception):
            me.close()
