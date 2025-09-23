from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from fastapi.testclient import TestClient
import pytest

from src.application.ops_console import (
    CHINA_TZ,
    ExecutionEnvelope,
    MetricPoint,
    MetricsSummary,
    OperationsConsoleService,
    OperationsStatusState,
    RunbookExecution,
    RunbookRequest,
    TimeseriesPoint,
    TimeseriesSeries,
)
from src.config import AppSettings
from src.infrastructure.http.ops_api import RunbookExecuteResponse, create_app

TOKEN = "test-token"


class DummyService:
    async def execute(self, request: RunbookRequest) -> ExecutionEnvelope:
        now = datetime.now(CHINA_TZ)
        execution = RunbookExecution(
            request_id=request.request_id or "req",
            command=request.command,
            mode=request.mode,
            window=request.window,
            profile=request.profile,
            config=request.config,
            exit_code=0,
            status="success",
            started_at=now,
            finished_at=now,
            duration_ms=0,
            logs=[],
            raw_output=[],
            metadata={},
        )
        return ExecutionEnvelope(runbook=execution, health=None)

    async def get_status(self) -> OperationsStatusState:
        state = OperationsStatusState()
        state.last_updated_at = datetime.now(CHINA_TZ)
        return state

    async def get_metrics_summary(self) -> MetricsSummary:
        now = datetime.now(CHINA_TZ)
        return MetricsSummary(
            coverage_ratio=MetricPoint(metric="coverage", value=0.99, updated_at=now),
            throughput_mps=MetricPoint(metric="throughput", value=5000, updated_at=now),
            failover_latency_ms=MetricPoint(
                metric="latency", value=1500, updated_at=now
            ),
            runbook_exit_code=MetricPoint(metric="exit", value=0, updated_at=now),
            consumer_backlog_messages=MetricPoint(
                metric="backlog", value=10, updated_at=now
            ),
        )

    async def get_timeseries(
        self,
        metric: str,
        *,
        minutes: int,
        step_seconds: int = 60,
    ) -> TimeseriesSeries:
        _ = (metric, minutes, step_seconds)
        now = datetime.now(CHINA_TZ)
        return TimeseriesSeries(
            metric=metric,
            unit="msg/s",
            points=[TimeseriesPoint(timestamp=now, value=123.0)],
        )


@pytest.fixture
def settings(tmp_path) -> AppSettings:
    status_dir = tmp_path / "status"
    health_dir = tmp_path / "health"
    status_dir.mkdir()
    health_dir.mkdir()
    return AppSettings.model_validate(
        {
            "ops_api_tokens": (TOKEN,),
            "ops_status_file": status_dir / "ops.json",
            "ops_health_output_dir": health_dir,
        }
    )


def _make_client(
    settings: AppSettings,
    *,
    allowed_tokens: set[str] | None,
) -> TestClient:
    app = create_app(
        settings,
        service=cast(OperationsConsoleService, DummyService()),
        allowed_tokens=allowed_tokens,
    )
    return TestClient(app)


def test_require_token_returns_503_when_not_configured(settings: AppSettings) -> None:
    empty_tokens = settings.model_copy(update={"ops_api_tokens": ()})
    client = _make_client(empty_tokens, allowed_tokens=set())
    response = client.get("/api/ops/status")
    assert response.status_code == 503


def test_require_token_missing_header_returns_401(settings: AppSettings) -> None:
    client = _make_client(settings, allowed_tokens=None)
    response = client.get("/api/ops/status")
    assert response.status_code == 401


def test_require_token_invalid_scheme(settings: AppSettings) -> None:
    client = _make_client(settings, allowed_tokens=None)
    response = client.get(
        "/api/ops/status",
        headers={"Authorization": "Basic abc"},
    )
    assert response.status_code == 401


def test_require_token_unauthorized_token(settings: AppSettings) -> None:
    client = _make_client(settings, allowed_tokens=None)
    response = client.get(
        "/api/ops/status",
        headers={"Authorization": "Bearer wrong"},
    )
    assert response.status_code == 403


def test_execute_runbook_succeeds(settings: AppSettings) -> None:
    client = _make_client(settings, allowed_tokens=None)
    payload: dict[str, Any] = {
        "command": "start",
        "mode": "mock",
        "window": "day",
        "profile": "live",
        "request_id": "req-123",
    }
    response = client.post(
        "/api/ops/runbooks/execute",
        json=payload,
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert response.status_code == 200
    assert RunbookExecuteResponse(**response.json()).runbook.request_id == "req-123"


def test_metrics_summary_endpoint_returns_payload(settings: AppSettings) -> None:
    client = _make_client(settings, allowed_tokens=None)
    response = client.get(
        "/api/ops/metrics/summary",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert response.status_code == 200
    assert response.json()["throughput_mps"]["value"] == 5000


def test_timeseries_endpoint_success(settings: AppSettings) -> None:
    client = _make_client(settings, allowed_tokens=None)
    response = client.get(
        "/api/ops/metrics/timeseries",
        params={"metric": "md_throughput_mps", "minutes": 5},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["points"][0]["value"] == 123.0
