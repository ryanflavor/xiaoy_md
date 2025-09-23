from __future__ import annotations

import logging
import types
from types import SimpleNamespace
from typing import Any


def _install_stubs(monkeypatch) -> None:
    # vnpy.event stub
    mod_event = types.ModuleType("vnpy.event")

    class Event:  # type: ignore[pyglyf-type]
        def __init__(self, data: Any) -> None:
            self.data = data

    class EventEngine:  # type: ignore[pyglyf-type]
        def __init__(self) -> None:
            self.handlers: dict[str, list[Any]] = {}
            self.stopped = False

        def register(self, name: str, handler: Any) -> None:
            self.handlers.setdefault(name, []).append(handler)
            if name in {"eLog", "EVENT_LOG"}:
                handler(SimpleNamespace(data=SimpleNamespace(msg="行情服务器登录成功")))

        def emit(self, name: str, payload: Any) -> None:
            for handler in self.handlers.get(name, []):
                handler(payload)

        def stop(self) -> None:
            self.stopped = True

    mod_event.Event = Event  # type: ignore[attr-defined]
    mod_event.EventEngine = EventEngine  # type: ignore[attr-defined]
    monkeypatch.setitem(__import__("sys").modules, "vnpy.event", mod_event)

    # vnpy.trader.object stub
    mod_obj = types.ModuleType("vnpy.trader.object")

    class Exchange(str):  # type: ignore[pyglyf-type]
        __slots__ = ()

        def __new__(cls, s: str):  # type: ignore[override]
            return str.__new__(cls, s)

    class SubscribeRequest:  # type: ignore[pyglyf-type]
        def __init__(self, symbol: str, exchange: Any) -> None:
            self.symbol = symbol
            self.exchange = exchange

    mod_obj.Exchange = Exchange  # type: ignore[attr-defined]
    mod_obj.SubscribeRequest = SubscribeRequest  # type: ignore[attr-defined]
    monkeypatch.setitem(__import__("sys").modules, "vnpy.trader.object", mod_obj)

    # vnpy_ctp stub
    mod_ctp = types.ModuleType("vnpy_ctp")

    class _ApiRecorder:
        def __init__(self, sink: list[str], prefix: str) -> None:
            self._sink = sink
            self._prefix = prefix

        def req_qry_instrument(self) -> None:
            self._sink.append(f"{self._prefix}.req_qry_instrument")

        def query_instrument(self) -> None:
            self._sink.append(f"{self._prefix}.query_instrument")

        def qry_instrument(self) -> None:
            self._sink.append(f"{self._prefix}.qry_instrument")

    class CtpGateway:  # type: ignore[pyglyf-type]
        def __init__(self) -> None:
            self.on_tick: Any | None = None
            self.subbed: list[Any] = []
            self.invocations: list[str] = []
            self.td_api = _ApiRecorder(self.invocations, "td_api")
            self.md_api = _ApiRecorder(self.invocations, "md_api")

        def subscribe(self, sub: Any) -> None:
            self.subbed.append(sub)

        def query_contract(self) -> None:
            self.invocations.append("gateway.query_contract")

    mod_ctp.CtpGateway = CtpGateway  # type: ignore[attr-defined]
    monkeypatch.setitem(__import__("sys").modules, "vnpy_ctp", mod_ctp)

    # vnpy.trader.engine stub
    mod_engine = types.ModuleType("vnpy.trader.engine")
    mod_engine.LAST_ME = None  # type: ignore[attr-defined]

    class MainEngine:  # type: ignore[pyglyf-type]
        def __init__(self, ee: Any) -> None:
            self.ee = ee
            self.gateways: dict[str, Any] = {}
            self.subs: list[tuple[str, Any]] = []
            self.contracts: dict[str, object] = {}
            self.invocations: list[str] = []
            self.closed = False
            mod_engine.LAST_ME = self  # type: ignore[attr-defined]

        def add_gateway(self, gw_cls: Any) -> None:
            self.gateways["CTP"] = gw_cls()

        def connect(self, *args: Any, **kwargs: Any) -> None:  # noqa: ARG002
            # Whenever connect happens, emit sample contract/log events
            handlers = list(self.ee.handlers.get("eContract", []))
            evt_contract = SimpleNamespace(data=SimpleNamespace(vt_symbol="rb888.SHFE"))
            for handler in handlers:
                handler(evt_contract)
            self.contracts = {"rb999.SHFE": object()}

        def get_gateway(self, name: str) -> Any:
            return self.gateways.get(name)

        def subscribe(self, sub: Any, name: str) -> None:
            self.subs.append((name, sub))

        def query_contract(self) -> None:
            self.invocations.append("main_engine.query_contract")

        def req_qry_instrument(self) -> None:
            self.invocations.append("main_engine.req_qry_instrument")

        def close(self) -> None:
            self.closed = True

    mod_engine.MainEngine = MainEngine  # type: ignore[attr-defined]
    monkeypatch.setitem(__import__("sys").modules, "vnpy.trader.engine", mod_engine)


def _should_shutdown_immediately() -> bool:
    return True


def test_attaches_on_tick_and_subscribes(monkeypatch) -> None:
    _install_stubs(monkeypatch)
    # Import after stubbing
    from src.infrastructure import ctp_live_connector as lc

    received: list[Any] = []
    lc.set_on_tick(lambda t: received.append(t))

    # Ensure env symbol present
    monkeypatch.setenv("CTP_SYMBOL", "rb9999.SHFE")

    # Run connector (should exit immediately)
    lc.live_gateway_connect({"k": "v"}, _should_shutdown_immediately)

    # Access last engine and gateway to verify
    me = __import__("sys").modules["vnpy.trader.engine"].LAST_ME  # type: ignore[attr-defined]
    assert me is not None
    assert me.subs, "subscribe via MainEngine expected"
    _, sub = me.subs[0]
    assert getattr(sub, "symbol", None) == "rb9999"

    gw = me.get_gateway("CTP")
    assert callable(getattr(gw, "on_tick", None))

    # Simulate a tick to ensure forwarding triggers our callback
    fake_tick = object()
    gw.on_tick(fake_tick)
    assert received
    assert received[0] is fake_tick


def test_event_engine_forwarding(monkeypatch) -> None:
    _install_stubs(monkeypatch)
    from src.infrastructure import ctp_live_connector as lc

    received: list[Any] = []
    lc.set_on_tick(lambda t: received.append(t))
    monkeypatch.setenv("CTP_SYMBOL", "rb9999.SHFE")

    lc.live_gateway_connect({}, _should_shutdown_immediately)

    # Retrieve eTick handler registered by the connector and simulate event
    ee = __import__("sys").modules["vnpy.event"]
    handler = ee.EventEngine.__call__.__self__.handlers.get("eTick", None) if False else None  # type: ignore[attr-defined]

    # Above line won't work due to how we instantiated; access through LAST_ME
    me = __import__("sys").modules["vnpy.trader.engine"].LAST_ME  # type: ignore[attr-defined]
    # The engine instance holds reference to ee via me.ee
    handlers = me.ee.handlers.get("eTick", [])
    assert handlers
    handler = handlers[0]
    assert callable(handler)
    fake_evt = types.SimpleNamespace(data=object())
    handler(fake_evt)
    assert received


def test_build_setting_from_env_normalizes(monkeypatch) -> None:
    _install_stubs(monkeypatch)
    from src.infrastructure import ctp_live_connector as lc

    monkeypatch.setenv("CTP_USER_ID", "u01")
    monkeypatch.setenv("CTP_PASSWORD", "pass")
    monkeypatch.setenv("CTP_BROKER_ID", "b01")
    monkeypatch.setenv("CTP_TD_ADDRESS", "127.0.0.1:5002")
    monkeypatch.setenv("CTP_MD_ADDRESS", "tcp://1.2.3.4:5001")
    monkeypatch.setenv("CTP_APP_ID", "app")
    monkeypatch.setenv("CTP_AUTH_CODE", "auth")

    setting = lc._build_setting_from_env()  # noqa: SLF001
    assert setting["用户名"] == "u01"
    assert setting["密码"] == "pass"
    assert setting["交易服务器"] == "tcp://127.0.0.1:5002"
    assert setting["行情服务器"] == "tcp://1.2.3.4:5001"


def test_subscribe_queue_drain_prefers_main_engine(monkeypatch, caplog) -> None:
    _install_stubs(monkeypatch)
    from src.infrastructure import ctp_live_connector as lc

    lc._SUBSCRIBE_QUEUE.clear()  # noqa: SLF001
    lc._SEEN_SUBS.clear()  # noqa: SLF001

    lc.request_subscribe("rb111.SHFE")
    lc.request_subscribe("rb111.SHFE")  # duplicate ignored
    lc.request_subscribe("invalid")  # ignored due to missing exchange part

    ee, me, gw = lc._connect_components({})  # noqa: SLF001
    assert len(lc._SUBSCRIBE_QUEUE) == 1  # noqa: SLF001

    with caplog.at_level("INFO"):
        lc._drain_subscribe_queue(logging.getLogger(__name__), me, gw)  # noqa: SLF001

    assert not lc._SUBSCRIBE_QUEUE  # noqa: SLF001
    assert any("bridge_subscribed" in record.message for record in caplog.records)
    assert me.subs, "MainEngine.subscribe expected"


def test_subscribe_queue_fallbacks_to_gateway(monkeypatch, caplog) -> None:
    _install_stubs(monkeypatch)
    from src.infrastructure import ctp_live_connector as lc

    lc._SUBSCRIBE_QUEUE.clear()  # noqa: SLF001
    lc._SEEN_SUBS.clear()  # noqa: SLF001
    lc.request_subscribe("rb222.SHFE")

    _, me, gw = lc._connect_components({})  # noqa: SLF001

    def _boom(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError

    me.subscribe = _boom  # type: ignore[assignment]

    with caplog.at_level("INFO"):
        lc._drain_subscribe_queue(logging.getLogger(__name__), me, gw)  # noqa: SLF001

    assert gw.subbed, "Gateway.subscribe should handle fallback"
    assert any("bridge_subscribed_gw" in rec.message for rec in caplog.records)


def test_query_all_contracts_returns_symbols(monkeypatch) -> None:
    _install_stubs(monkeypatch)
    from src.infrastructure import ctp_live_connector as lc

    monkeypatch.setenv("CTP_USER_ID", "u")
    monkeypatch.setenv("CTP_PASSWORD", "p")
    monkeypatch.setenv("CTP_BROKER_ID", "b")

    captured: list[list[str]] = []
    lc.set_on_contracts(lambda symbols: captured.append(symbols))

    result = lc.query_all_contracts(_timeout_s=0.2)

    assert result
    assert result == sorted(result)
    me = __import__("sys").modules["vnpy.trader.engine"].LAST_ME  # type: ignore[attr-defined]
    assert me.closed is True
    assert me.invocations  # query attempts recorded
    gw = me.get_gateway("CTP")
    assert gw.invocations  # type: ignore[attr-defined]
    assert captured
    assert captured[0] == result
