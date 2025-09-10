from __future__ import annotations

import asyncio
import contextlib
import importlib
import os

import pytest

from src.config import AppSettings
from src.infrastructure.ctp_adapter import CTPGatewayAdapter

pytestmark = [pytest.mark.integration, pytest.mark.e2e, pytest.mark.slow]


def _load_connector_from_env():
    target = os.environ.get("CTP_GATEWAY_CONNECT")
    if not target:
        raise ValueError
    if ":" in target:
        module_path, attr = target.split(":", 1)
    else:
        module_path, attr = target.rsplit(".", 1)
    module = importlib.import_module(module_path)
    fn = getattr(module, attr)
    if not callable(fn):
        raise TypeError
    return fn


@pytest.mark.asyncio
async def test_ctp_live_tick_flow() -> None:
    if os.environ.get("CTP_LIVE") != "1":
        pytest.skip("CTP_LIVE not set; skipping live CTP integration test.")

    required = [
        "CTP_BROKER_ID",
        "CTP_USER_ID",
        "CTP_PASSWORD",
        "CTP_MD_ADDRESS",
        "CTP_TD_ADDRESS",
        "CTP_APP_ID",
        "CTP_AUTH_CODE",
        "CTP_SYMBOL",
        "CTP_GATEWAY_CONNECT",
    ]
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        pytest.skip(f"Missing env vars for live test: {missing}")

    settings = AppSettings()
    gateway_connect = _load_connector_from_env()

    symbol = os.environ["CTP_SYMBOL"]
    adapter = CTPGatewayAdapter(settings, gateway_connect=gateway_connect)

    # attach callback for forwarding
    with contextlib.suppress(Exception):
        attr_name = "_on_tick"
        setattr(gateway_connect, attr_name, adapter.on_tick)

    # allow base symbol before contracts fully loaded
    base_symbol = symbol.split(".")[0]
    adapter.symbol_contract_map[base_symbol] = object()

    await adapter.connect()

    received = None

    async def consume_once() -> None:
        nonlocal received
        async for tick in adapter.receive_ticks():
            received = tick
            break

    try:
        await asyncio.wait_for(consume_once(), timeout=15.0)
    finally:
        await adapter.disconnect()

    assert received is not None
