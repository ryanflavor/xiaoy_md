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


def live_gateway_connect(  # noqa: PLR0912, PLR0915
    setting: dict[str, object], should_shutdown: Callable[[], bool]
) -> None:
    try:
        from vnpy.event import EventEngine  # type: ignore[import-untyped]
        from vnpy.trader.engine import MainEngine  # type: ignore[import-untyped]
        from vnpy.trader.object import (  # type: ignore[import-untyped]
            Exchange,
            SubscribeRequest,
        )
        from vnpy_ctp import CtpGateway  # type: ignore[import-untyped]
    except Exception as exc:
        raise RuntimeError from exc

    log = logging.getLogger(__name__)
    ee = EventEngine()
    me = MainEngine(ee)
    me.add_gateway(CtpGateway)

    # Connect (handle different signatures across versions)
    try:
        me.connect(setting, "CTP")
    except TypeError:
        me.connect("CTP", setting)

    # Resolve CTP gateway instance
    gw: Any | None = None
    try:
        gw = me.get_gateway("CTP")
    except Exception:  # noqa: BLE001
        gw = getattr(me, "gateways", {}).get("CTP")
    if gw is None:
        raise LookupError

    # Attach adapter-bound on_tick if provided
    cb = getattr(live_gateway_connect, "_on_tick", None)
    if cb is not None:

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
            from vnpy.event import Event

            def _on_event(evt: Event) -> None:
                try:
                    cb(getattr(evt, "data", evt))
                except Exception:
                    log.exception("bridge_on_tick_event_exception")

            ee.register("eTick", _on_event)
            log.info("bridge_event_on_tick_attached")
        except Exception:
            log.exception("bridge_event_on_tick_attach_failed")

    # Subscribe to vt_symbol if provided
    vt = os.environ.get("CTP_SYMBOL")
    if vt and "." in vt:
        # Wait briefly for market data login before subscribing
        md_ready = {"ok": False}
        try:
            from vnpy.event import Event

            def _on_log(evt: Event) -> None:
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

        sym, ex = vt.split(".", 1)
        try:
            ex_enum: Any = Exchange(ex)
        except Exception:  # noqa: BLE001
            ex_enum = ex
        sub = SubscribeRequest(symbol=sym, exchange=ex_enum)
        # Prefer MainEngine.subscribe, fallback to gateway.subscribe
        try:
            me.subscribe(sub, "CTP")
            log.info("bridge_subscribed", extra={"vt_symbol": vt})
        except Exception:  # noqa: BLE001
            try:
                gw.subscribe(sub)
                log.info("bridge_subscribed_gw", extra={"vt_symbol": vt})
            except Exception:
                log.exception("bridge_subscribe_failed", extra={"vt_symbol": vt})

    # Idle loop until shutdown
    try:
        while not should_shutdown():
            time.sleep(0.1)
    finally:
        import contextlib

        with contextlib.suppress(Exception):
            me.close()
