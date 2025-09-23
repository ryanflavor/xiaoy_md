"""vn.py-based live CTP connector tailored for the 2.2 bridge.

Provides `live_gateway_connect(setting, should_shutdown)` that:
- Connects to CTP via vn.py
- If `_on_tick` attribute is present on the function, forwards ticks to it
- Subscribes to `CTP_SYMBOL` from env
"""

from __future__ import annotations

from collections import deque
import contextlib
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


def set_on_contracts(callback: Any) -> None:
    """Public API to set contracts callback (one-shot aggregate).

    When live gateway completes contract query aggregation, it should invoke
    this callback with a list of vt_symbols.
    """
    name = "_on_contracts"
    setattr(live_gateway_connect, name, callback)


def _build_setting_from_env() -> dict[str, object]:
    """Build vn.py CTP setting dict from environment variables.

    Reads CTP_* variables and returns a mapping using Chinese keys expected by vn.py.
    """

    def _norm(addr: str | None) -> str:
        if not addr:
            return ""
        if addr.startswith(("tcp://", "ssl://")):
            return addr
        return f"tcp://{addr}"

    return {
        "用户名": os.environ.get("CTP_USER_ID") or "",
        "密码": os.environ.get("CTP_PASSWORD") or "",
        "经纪商代码": os.environ.get("CTP_BROKER_ID") or "",
        "交易服务器": _norm(os.environ.get("CTP_TD_ADDRESS")),
        "行情服务器": _norm(os.environ.get("CTP_MD_ADDRESS")),
        "产品名称": os.environ.get("CTP_APP_ID") or "",
        "授权编码": os.environ.get("CTP_AUTH_CODE") or "",
    }


def _connect_components(setting: dict[str, object]) -> tuple[Any, Any, Any]:
    """Create EventEngine, MainEngine, and CTP gateway; return (ee, me, gw)."""
    try:
        _event_engine_cls = __import__(
            "vnpy.event", fromlist=["EventEngine"]
        ).EventEngine
        _main_engine_cls = __import__(
            "vnpy.trader.engine", fromlist=["MainEngine"]
        ).MainEngine
        _ctp_gateway_cls = __import__("vnpy_ctp", fromlist=["CtpGateway"]).CtpGateway
    except Exception as exc:
        raise RuntimeError from exc

    ee = _event_engine_cls()
    me = _main_engine_cls(ee)
    me.add_gateway(_ctp_gateway_cls)

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


# In-process queue for cross-thread subscription requests from adapter
_SUBSCRIBE_QUEUE: deque[str] = deque()
_SEEN_SUBS: set[str] = set()


def request_subscribe(vt_symbol: str) -> None:
    """Enqueue a vt_symbol for live subscription by the connector loop.

    Thread-safe and idempotent: duplicates are ignored.
    """
    vt = (vt_symbol or "").strip()
    if not vt or "." not in vt:
        return
    # Avoid unbounded growth on duplicates
    if vt in _SEEN_SUBS:
        return
    _SEEN_SUBS.add(vt)
    _SUBSCRIBE_QUEUE.append(vt)


def _subscribe_symbol_env(log: logging.Logger, ee: Any, me: Any, gw: Any) -> None:
    """Subscribe to vt_symbol from env with brief MD login wait (one-time seed)."""
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

    _obj_mod = __import__(
        "vnpy.trader.object", fromlist=["Exchange", "SubscribeRequest"]
    )
    exchange_cls = _obj_mod.Exchange
    subscribe_req_cls = _obj_mod.SubscribeRequest

    sym, ex = vt.split(".", 1)
    try:
        ex_enum: Any = exchange_cls(ex)
    except Exception:  # noqa: BLE001
        ex_enum = ex
    sub = subscribe_req_cls(symbol=sym, exchange=ex_enum)
    try:
        me.subscribe(sub, "CTP")
        log.info("bridge_subscribed", extra={"vt_symbol": vt})
    except Exception:  # noqa: BLE001
        try:
            gw.subscribe(sub)
            log.info("bridge_subscribed_gw", extra={"vt_symbol": vt})
        except Exception:
            log.exception("bridge_subscribe_failed", extra={"vt_symbol": vt})


def _drain_subscribe_queue(log: logging.Logger, me: Any, gw: Any) -> None:
    """Apply queued subscribe requests (from adapter control plane)."""
    if not _SUBSCRIBE_QUEUE:
        return
    try:
        _obj_mod = __import__(
            "vnpy.trader.object", fromlist=["Exchange", "SubscribeRequest"]
        )
        exchange_cls = _obj_mod.Exchange
        subscribe_req_cls = _obj_mod.SubscribeRequest
    except Exception:  # noqa: BLE001
        # Unable to process without vn.py objects
        return

    while _SUBSCRIBE_QUEUE:
        vt = _SUBSCRIBE_QUEUE.popleft()
        try:
            sym, ex = vt.split(".", 1)
            try:
                ex_enum: Any = exchange_cls(ex)
            except Exception:  # noqa: BLE001
                ex_enum = ex
            sub = subscribe_req_cls(symbol=sym, exchange=ex_enum)
            try:
                me.subscribe(sub, "CTP")
                log.info("bridge_subscribed", extra={"vt_symbol": vt})
            except Exception:  # noqa: BLE001
                try:
                    gw.subscribe(sub)
                    log.info("bridge_subscribed_gw", extra={"vt_symbol": vt})
                except Exception:
                    log.exception("bridge_subscribe_failed", extra={"vt_symbol": vt})
        except Exception:
            log.exception("bridge_subscribe_request_invalid", extra={"vt_symbol": vt})


def live_gateway_connect(
    setting: dict[str, object], should_shutdown: Callable[[], bool]
) -> None:
    """Run vn.py session, attach forwarders, subscribe, and idle until shutdown."""
    log = logging.getLogger(__name__)
    ee, me, gw = _connect_components(setting)
    _attach_forwarders(log, ee, gw)
    _subscribe_symbol_env(log, ee, me, gw)

    # Idle loop until shutdown
    try:
        while not should_shutdown():
            # Drain cross-thread subscribe requests from adapter
            _drain_subscribe_queue(log, me, gw)
            time.sleep(0.1)
    finally:
        import contextlib

        with contextlib.suppress(Exception):
            me.close()


def query_all_contracts(_timeout_s: float = 1.0) -> list[str]:
    """Trigger vn.py contract discovery and aggregate vt_symbols (best-effort).

    - Connects using CTP_* from environment.
    - Subscribes to eContract events and accumulates ContractData.vt_symbol.
    - Attempts to call gateway-side query if available; otherwise relies on
      gateway to emit cached contracts upon connect.
    - Returns when timeout elapses. Closes resources before returning.
    """
    try:
        _event_engine_cls = __import__(
            "vnpy.event", fromlist=["EventEngine"]
        ).EventEngine
        _main_engine_cls = __import__(
            "vnpy.trader.engine", fromlist=["MainEngine"]
        ).MainEngine
        _ctp_gateway_cls = __import__("vnpy_ctp", fromlist=["CtpGateway"]).CtpGateway
    except Exception:  # noqa: BLE001
        return []

    ee = _event_engine_cls()
    me = _main_engine_cls(ee)
    me.add_gateway(_ctp_gateway_cls)

    # Accumulator for vt_symbols and simple progress flags
    vt_syms: set[str] = set()
    flags: dict[str, bool] = {"md_login": False, "settlement": False}

    # Listen for contract/log events
    try:
        try:
            _evt_mod = __import__(
                "vnpy.trader.event", fromlist=["EVENT_CONTRACT", "EVENT_LOG"]
            )
            evt_contract = getattr(_evt_mod, "EVENT_CONTRACT", "eContract")
            evt_log = getattr(_evt_mod, "EVENT_LOG", "eLog")
        except Exception:  # noqa: BLE001
            evt_contract, evt_log = "eContract", "eLog"

        def _on_contract(evt: Any) -> None:
            data = getattr(evt, "data", None)
            vt = getattr(data, "vt_symbol", None)
            if isinstance(vt, str) and vt:
                vt_syms.add(vt)

        ee.register(evt_contract, _on_contract)

        def _on_log(evt: Any) -> None:
            msg = getattr(getattr(evt, "data", None), "msg", "")
            if isinstance(msg, str):
                if "结算信息确认成功" in msg:
                    flags["settlement"] = True
                if "行情服务器登录成功" in msg:
                    flags["md_login"] = True

        ee.register(evt_log, _on_log)
    except Exception as e:  # noqa: BLE001
        logging.getLogger(__name__).debug(
            "contract_event_setup_failed", exc_info=True, extra={"error": str(e)}
        )

    # Connect
    setting = _build_setting_from_env()
    try:
        try:
            me.connect(setting, "CTP")
        except TypeError:
            me.connect("CTP", setting)
    except Exception:  # noqa: BLE001
        return []

    # Wait briefly for market data login / settlement info
    import time as _time

    wait_login_settlement_window = 2.0
    start = _time.time()
    while _time.time() - start < wait_login_settlement_window and not (
        flags["md_login"] or flags["settlement"]
    ):
        _time.sleep(0.05)

    # Attempt to trigger contract query if available
    try:
        gw = me.get_gateway("CTP")
    except Exception:  # noqa: BLE001
        gw = getattr(me, "gateways", {}).get("CTP")
    try:
        # Common patterns observed in CTP gateways: try multiple call sites
        candidates: list[tuple[Any, str]] = []
        # Gateway direct
        candidates.append((gw, "query_contract"))
        # Underlying APIs
        for api_name in ("td_api", "md_api"):
            api = getattr(gw, api_name, None)
            if api is not None:
                candidates.extend(
                    [
                        (api, fn_name)
                        for fn_name in (
                            "req_qry_instrument",
                            "query_instrument",
                            "qry_instrument",
                        )
                    ]
                )
        # Main engine (version-dependent)
        candidates.extend(
            [(me, fn_name) for fn_name in ("query_contract", "req_qry_instrument")]
        )

        for obj, name in candidates:
            fn = getattr(obj, name, None)
            if callable(fn):
                with contextlib.suppress(Exception):
                    fn()
    except Exception as e:  # noqa: BLE001
        logging.getLogger(__name__).debug(
            "contract_query_trigger_failed", exc_info=True, extra={"error": str(e)}
        )

    # Wait for results until timeout; also poll MainEngine.contracts as fallback

    deadline = _time.time() + float(max(0.1, _timeout_s))
    last_len = -1
    stable_cycles = 0
    stable_cycles_required = 5
    while _time.time() < deadline:
        # Poll direct cache on MainEngine (vn.py usually stores contracts here)
        contracts = getattr(me, "contracts", {})
        if isinstance(contracts, dict) and contracts:
            vt_syms.update([str(k) for k in contracts])
        cur_len = len(vt_syms)
        if cur_len == last_len:
            stable_cycles += 1
            # If stable for ~5 cycles (~250ms), we likely have a final set during off-hours
            if stable_cycles >= stable_cycles_required and cur_len > 0:
                break
        else:
            last_len = cur_len
            stable_cycles = 0
        _time.sleep(0.05)

    # Invoke one-shot callback if set
    cb = getattr(live_gateway_connect, "_on_contracts", None)
    if callable(cb):  # pragma: no cover - smoke/live usage
        with contextlib.suppress(Exception):
            cb(sorted(vt_syms))

    # Cleanup
    import contextlib as _ctx

    with _ctx.suppress(Exception):
        me.close()
    with _ctx.suppress(Exception):
        ee.stop()

    return sorted(vt_syms)
