from __future__ import annotations

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
            self.handlers: dict[str, Any] = {}

        def register(self, name: str, handler: Any) -> None:
            self.handlers[name] = handler
            # Immediately simulate MD login to skip waits
            if name == "eLog":
                handler(SimpleNamespace(data=SimpleNamespace(msg="行情服务器登录成功")))

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

    class CtpGateway:  # type: ignore[pyglyf-type]
        def __init__(self) -> None:
            self.on_tick: Any | None = None
            self.subbed: list[Any] = []

        def subscribe(self, sub: Any) -> None:
            self.subbed.append(sub)

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
            mod_engine.LAST_ME = self  # type: ignore[attr-defined]

        def add_gateway(self, gw_cls: Any) -> None:
            self.gateways["CTP"] = gw_cls()

        def connect(self, *args: Any, **kwargs: Any) -> None:  # noqa: ARG002
            return None

        def get_gateway(self, name: str) -> Any:
            return self.gateways.get(name)

        def subscribe(self, sub: Any, name: str) -> None:
            self.subs.append((name, sub))

        def close(self) -> None:
            return None

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
    handler = me.ee.handlers.get("eTick")
    assert callable(handler)
    fake_evt = types.SimpleNamespace(data=object())
    handler(fake_evt)
    assert received
