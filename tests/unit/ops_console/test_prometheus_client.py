from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Self

import httpx
import pytest

from src.application.prometheus_client import PrometheusClient, PrometheusSample


class DummyResponse:
    """Simple HTTPX response stub."""

    def __init__(self, payload: dict[str, Any]) -> None:
        """Store the payload to return from json()."""
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class DummyAsyncClient:
    """Async context manager mimicking httpx.AsyncClient."""

    def __init__(self, *, payload: dict[str, Any], **_: Any) -> None:
        """Capture payload for responses."""
        self._payload = payload

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        return None

    async def get(self, url: str, params: dict[str, Any]) -> DummyResponse:
        _ = (url, params)
        return DummyResponse(self._payload)


@pytest.mark.asyncio
async def test_query_latest_parses_success(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime.now(UTC)
    payload = {
        "status": "success",
        "data": {
            "result": [
                {
                    "value": [
                        str(now.timestamp()),
                        "123.45",
                    ]
                }
            ]
        },
    }
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: DummyAsyncClient(payload=payload, **kwargs),
    )
    client = PrometheusClient("http://prom.test")
    sample = await client.query_latest("md_metric")
    assert isinstance(sample, PrometheusSample)
    assert sample.value == pytest.approx(123.45)


@pytest.mark.asyncio
async def test_query_range_returns_samples(monkeypatch: pytest.MonkeyPatch) -> None:
    base = datetime.now(UTC)
    payload = {
        "status": "success",
        "data": {
            "result": [
                {
                    "values": [
                        [str(base.timestamp()), "100"],
                        [str(base.timestamp() + 60), "200"],
                    ]
                }
            ]
        },
    }
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: DummyAsyncClient(payload=payload, **kwargs),
    )
    client = PrometheusClient("http://prom.test")
    series = await client.query_range("md_metric", minutes=5)
    assert [sample.value for sample in series] == [100.0, 200.0]


class FailingAsyncClient:
    """Async client stub that raises request errors."""

    def __init__(self, **_: Any) -> None:
        """Accept arbitrary ctor kwargs to match httpx client."""

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        return None

    async def get(self, url: str, params: dict[str, Any]) -> DummyResponse:
        _ = (url, params)
        raise httpx.RequestError("boom", request=None)


@pytest.mark.asyncio
async def test_query_latest_handles_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "AsyncClient", FailingAsyncClient)
    client = PrometheusClient("http://prom.test")
    sample = await client.query_latest("md_metric")
    assert sample is None


@pytest.mark.asyncio
async def test_query_latest_returns_none_when_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {"status": "success", "data": {"result": []}}
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: DummyAsyncClient(payload=payload, **kwargs),
    )
    client = PrometheusClient("http://prom.test")
    assert await client.query_latest("md_metric") is None


@pytest.mark.asyncio
async def test_query_range_handles_invalid_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {"status": "error", "data": {}}
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: DummyAsyncClient(payload=payload, **kwargs),
    )
    client = PrometheusClient("http://prom.test")
    assert await client.query_range("metric", minutes=5) == []


@pytest.mark.asyncio
async def test_query_range_returns_empty_when_no_series(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {"status": "success", "data": {"result": []}}
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: DummyAsyncClient(payload=payload, **kwargs),
    )
    client = PrometheusClient("http://prom.test")
    assert await client.query_range("metric", minutes=5) == []
