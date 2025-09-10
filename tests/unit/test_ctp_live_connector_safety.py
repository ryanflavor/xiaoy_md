from __future__ import annotations

import sys

import pytest

from src.infrastructure.ctp_live_connector import live_gateway_connect


def test_live_gateway_connect_raises_without_vnpy(monkeypatch):
    # Ensure vnpy modules are not importable by poisoning sys.modules
    for mod in [
        "vnpy",
        "vnpy.event",
        "vnpy.trader.engine",
        "vnpy.trader.object",
        "vnpy_ctp",
    ]:
        monkeypatch.setitem(sys.modules, mod, None)

    with pytest.raises(RuntimeError):
        live_gateway_connect({}, lambda: True)
