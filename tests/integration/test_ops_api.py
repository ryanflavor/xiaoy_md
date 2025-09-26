from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from httpx import ASGITransport, AsyncClient
import pytest

from src.application.ops_console import (
    HealthCheckExecution,
    HealthCheckExecutorProtocol,
    OperationsConsoleService,
    OperationsStatusState,
    RunbookExecution,
    RunbookExecutorProtocol,
    RunbookRequest,
)
from src.application.prometheus_client import PrometheusSample
from src.config import AppSettings
from src.infrastructure.http.ops_api import create_app

CHINA_TZ = ZoneInfo("Asia/Shanghai")
TOKEN = "test-token"


class InMemoryStatusRepository:
    def __init__(self) -> None:
        """Initialize in-memory status storage."""
        self.state = OperationsStatusState()

    async def load(self) -> OperationsStatusState:
        return self.state

    async def save(self, state: OperationsStatusState) -> None:
        self.state = state


class FakeRunbookExecutor(RunbookExecutorProtocol):
    def __init__(self) -> None:
        """Capture executed requests for inspection."""
        self.calls: list[RunbookRequest] = []

    async def execute(self, request: RunbookRequest) -> RunbookExecution:
        request = request.ensure_request_id()
        self.calls.append(request)
        now = datetime.now(CHINA_TZ)
        metadata = {"mock": True, "reason": request.reason}
        return RunbookExecution(
            request_id=request.request_id or "",
            command=request.command,
            mode=request.mode,
            window=request.window,
            profile=request.profile,
            config=request.normalized_config(),
            exit_code=0,
            status="success",
            started_at=now,
            finished_at=now,
            duration_ms=0,
            logs=[{"message": "ok", "mock": True}],
            raw_output=['{"message":"ok"}'],
            metadata={k: v for k, v in metadata.items() if v is not None},
        )


class FakeHealthExecutor(HealthCheckExecutorProtocol):
    async def run(self, request: RunbookRequest) -> HealthCheckExecution:
        request = request.ensure_request_id()
        now = datetime.now(CHINA_TZ)
        report: dict[str, Any] = {
            "generated_at": now.isoformat(),
            "coverage_ratio": 0.999,
            "expected_total": 1280,
            "active_total": 1280,
            "missing_contracts": [],
            "stalled_contracts": [],
            "warnings": [],
            "errors": [],
            "exit_code": 0,
        }
        return HealthCheckExecution(
            request_id=request.request_id or "",
            mode=request.mode,
            started_at=now,
            finished_at=now,
            exit_code=0,
            report=report,
            raw_output=["health"],
            metadata={"mock": True},
        )


class FakePrometheusClient:
    def __init__(self) -> None:
        """Seed deterministic samples for tests."""
        now = datetime.now(CHINA_TZ)
        self.samples = {
            "md_throughput_mps": PrometheusSample(
                metric="md_throughput_mps", value=5400.0, timestamp=now
            ),
            "md_failover_latency_ms": PrometheusSample(
                metric="md_failover_latency_ms", value=1800.0, timestamp=now
            ),
            "md_runbook_exit_code": PrometheusSample(
                metric="md_runbook_exit_code", value=0.0, timestamp=now
            ),
            "consumer_backlog_messages": PrometheusSample(
                metric="consumer_backlog_messages", value=12.0, timestamp=now
            ),
        }

    def _resolve(self, metric: str) -> PrometheusSample | None:
        key = metric
        if metric.startswith("max(") and metric.endswith(")"):
            key = metric[4:-1]
        elif metric.startswith("max_over_time(") and metric.endswith(")"):
            inner = metric[len("max_over_time(") : -1]
            if inner.endswith("]") and "[" in inner:
                key = inner.split("[", 1)[0]
            else:
                key = inner
        return self.samples.get(key)

    async def query_latest(self, metric: str) -> PrometheusSample | None:
        return self._resolve(metric)

    async def query_range(
        self, metric: str, *, minutes: int, step_seconds: int = 60
    ) -> list[PrometheusSample]:
        _ = (minutes, step_seconds)
        sample = self._resolve(metric)
        return [sample] if sample else []


@pytest.fixture
def fake_service() -> OperationsConsoleService:
    repo = InMemoryStatusRepository()
    return OperationsConsoleService(
        runbook_executor=FakeRunbookExecutor(),
        health_executor=FakeHealthExecutor(),
        status_repository=repo,
        prometheus_client=FakePrometheusClient(),
    )


@pytest.fixture
def test_app(tmp_path, fake_service: OperationsConsoleService):
    settings = AppSettings.model_validate(
        {
            "ops_api_tokens": (TOKEN,),
            "ops_status_file": tmp_path / "status.json",
            "ops_health_output_dir": tmp_path / "health",
        }
    )
    return create_app(
        settings,
        service=fake_service,
        allowed_tokens={TOKEN},
    )


@pytest.fixture
async def client(test_app):
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://ops.test") as client:
        yield client


@pytest.mark.asyncio
async def test_execute_runbook_mock_mode(client: AsyncClient):
    payload = {
        "command": "start",
        "mode": "mock",
        "window": "day",
        "profile": "live",
        "request_id": "req-123",
    }
    resp = await client.post(
        "/api/ops/runbooks/execute",
        json=payload,
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["runbook"]["status"] == "success"
    assert data["runbook"]["request_id"] == "req-123"
    assert data["runbook"]["logs"][0]["message"] == "ok"

    # idempotent re-execution
    resp_repeat = await client.post(
        "/api/ops/runbooks/execute",
        json=payload,
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert resp_repeat.status_code == 200
    assert resp_repeat.json() == data


@pytest.mark.asyncio
async def test_health_check_returns_snapshot(client: AsyncClient):
    payload = {
        "command": "health_check",
        "mode": "mock",
        "window": "day",
        "profile": "live",
        "request_id": "hc-1",
    }
    resp = await client.post(
        "/api/ops/runbooks/execute",
        json=payload,
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["health"]["coverage_ratio"] == pytest.approx(0.999, rel=1e-6)
    assert body["runbook"]["command"] == "health_check"


@pytest.mark.asyncio
async def test_status_endpoint_reflects_recent_history(client: AsyncClient):
    headers = {"Authorization": f"Bearer {TOKEN}"}
    await client.post(
        "/api/ops/runbooks/execute",
        json={
            "command": "start",
            "mode": "mock",
            "window": "day",
            "profile": "live",
            "request_id": "status-runbook",
        },
        headers=headers,
    )
    await client.post(
        "/api/ops/runbooks/execute",
        json={
            "command": "health_check",
            "mode": "mock",
            "window": "day",
            "profile": "live",
            "request_id": "status-health",
        },
        headers=headers,
    )
    resp = await client.get("/api/ops/status", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["last_runbook"]["request_id"] == "status-health"
    assert data["last_health"]["request_id"] == "status-health"
    assert len(data["runbook_history"]) >= 2


@pytest.mark.asyncio
async def test_metrics_summary_combines_prometheus_and_health(client: AsyncClient):
    headers = {"Authorization": f"Bearer {TOKEN}"}
    # seed health snapshot for coverage
    await client.post(
        "/api/ops/runbooks/execute",
        json={
            "command": "health_check",
            "mode": "mock",
            "window": "day",
            "profile": "live",
            "request_id": "metrics-health",
        },
        headers=headers,
    )
    resp = await client.get("/api/ops/metrics/summary", headers=headers)
    assert resp.status_code == 200
    summary = resp.json()
    assert summary["coverage_ratio"]["value"] == pytest.approx(0.999, rel=1e-6)
    assert summary["throughput_mps"]["value"] == 5400.0
    assert summary["failover_latency_ms"]["value"] == 1800.0


@pytest.mark.asyncio
async def test_authentication_required(client: AsyncClient):
    resp = await client.get("/api/ops/status")
    assert resp.status_code == 401
