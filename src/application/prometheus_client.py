"""Prometheus HTTP client utilities for the operations console."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx

CHINA_TZ = ZoneInfo("Asia/Shanghai")
VALUE_FIELDS_MIN = 2


@dataclass(slots=True)
class PrometheusSample:
    """Single Prometheus time series sample."""

    metric: str
    value: float
    timestamp: datetime


class PrometheusClient:
    """Thin async client for Prometheus HTTP API queries."""

    def __init__(self, base_url: str | None, *, timeout: float = 3.0) -> None:
        """Store base URL and timeout for subsequent HTTP calls."""
        self._base_url = base_url.rstrip("/") if base_url else ""
        self._timeout = timeout

    async def query_latest(self, metric: str) -> PrometheusSample | None:
        """Fetch the most recent sample for a metric."""
        if not self._base_url:
            return None
        url = f"{self._base_url}/api/v1/query"
        params = {"query": metric}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(url, params=params)
            response.raise_for_status()
        except (httpx.HTTPStatusError, httpx.RequestError):
            return None
        payload: dict[str, Any] = response.json()
        if payload.get("status") != "success":
            return None
        results = payload.get("data", {}).get("result") or []
        if not results:
            return None
        raw_value = results[0].get("value")
        parsed = _parse_value(raw_value)
        if parsed is None:
            return None
        timestamp, value = parsed
        return PrometheusSample(metric=metric, value=value, timestamp=timestamp)

    async def query_range(
        self,
        metric: str,
        *,
        minutes: int,
        step_seconds: int = 60,
    ) -> list[PrometheusSample]:
        """Fetch a range of samples for a metric."""
        if not self._base_url:
            return []
        end = datetime.now(UTC)
        start = end - timedelta(minutes=max(1, minutes))
        url = f"{self._base_url}/api/v1/query_range"
        params = {
            "query": metric,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "step": f"{max(1, step_seconds)}s",
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(url, params=params)
            response.raise_for_status()
        except (httpx.HTTPStatusError, httpx.RequestError):
            return []
        payload: dict[str, Any] = response.json()
        if payload.get("status") != "success":
            return []
        results = payload.get("data", {}).get("result") or []
        if not results:
            return []
        series = results[0].get("values") or []
        samples: list[PrometheusSample] = []
        for raw_value in series:
            parsed = _parse_value(raw_value)
            if parsed is None:
                continue
            timestamp, value = parsed
            samples.append(
                PrometheusSample(metric=metric, value=value, timestamp=timestamp)
            )
        return samples


def _parse_value(raw_value: Any) -> tuple[datetime, float] | None:
    if not raw_value or len(raw_value) < VALUE_FIELDS_MIN:
        return None
    try:
        timestamp = datetime.fromtimestamp(float(raw_value[0]), tz=UTC).astimezone(
            CHINA_TZ
        )
        value = float(raw_value[1])
    except (TypeError, ValueError):
        return None
    return timestamp, value
