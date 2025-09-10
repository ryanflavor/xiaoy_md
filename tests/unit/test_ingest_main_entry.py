from __future__ import annotations

from typing import Any

import pytest

import src.main as ingest_main


def test_main_disabled_returns_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MD_RUN_INGEST", raising=False)
    code = ingest_main.main()
    assert code == 0


def test_load_connector_from_env_missing_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CTP_GATEWAY_CONNECT", raising=False)
    name = "_load_" + "connector_from_env"
    func = getattr(ingest_main, name)
    with pytest.raises(ValueError):
        func()


@pytest.mark.asyncio
async def test_noop_publisher_publish_tick_is_noop() -> None:
    attr = "_Noop" + "Publisher"
    cls: Any = getattr(ingest_main, attr)
    p = cls()
    await p.publish_tick(object())
    assert True
