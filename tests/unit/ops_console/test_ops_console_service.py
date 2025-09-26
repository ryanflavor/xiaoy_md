from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest

from src.application.ops_console import (
    CHINA_TZ,
    HEALTH_HISTORY_LIMIT,
    RUNBOOK_HISTORY_LIMIT,
    HealthCheckExecution,
    HealthSnapshot,
    JsonStatusRepository,
    OperationsConsoleService,
    OperationsStatusState,
    RunbookCommand,
    RunbookExecution,
    RunbookExecutor,
    RunbookRequest,
    _try_parse_json,
)
from src.application.prometheus_client import PrometheusSample


class InMemoryStatusRepository:
    """In-memory implementation of the status repository."""

    def __init__(self) -> None:
        """Initialize repository with empty state."""
        self.state = OperationsStatusState()

    async def load(self) -> OperationsStatusState:
        return self.state

    async def save(self, state: OperationsStatusState) -> None:
        self.state = state


class StubRunbookExecutor:
    """Collects runbook execute calls for assertions."""

    def __init__(self) -> None:
        """Prepare container for captured calls."""
        self.calls: list[RunbookRequest] = []

    async def execute(self, request: RunbookRequest) -> RunbookExecution:
        self.calls.append(request)
        now = datetime.now(CHINA_TZ)
        return RunbookExecution(
            request_id=request.request_id or "generated",
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
            logs=[{"message": "ok"}],
            raw_output=(
                ["runbook"] if request.command != RunbookCommand.HEALTH_CHECK else []
            ),
            metadata={},
        )


class StubHealthExecutor:
    """Captures health-check invocations."""

    def __init__(self) -> None:
        """Initialize the call log."""
        self.calls: list[RunbookRequest] = []

    async def run(self, request: RunbookRequest) -> HealthCheckExecution:
        self.calls.append(request)
        now = datetime.now(CHINA_TZ)
        report = {
            "generated_at": now.isoformat(),
            "coverage_ratio": 0.997,
            "expected_total": 120,
            "active_total": 118,
            "missing_contracts": ["rb2401.SHFE"],
            "stalled_contracts": [],
            "warnings": [],
            "errors": [],
            "exit_code": 0,
        }
        return HealthCheckExecution(
            request_id=request.request_id or "health-1",
            mode=request.mode,
            started_at=now,
            finished_at=now,
            exit_code=0,
            report=report,
            raw_output=["health"],
            metadata={"mock": True},
        )


class StubPrometheusClient:
    """Stub Prometheus client returning canned samples."""

    def __init__(self) -> None:
        """Seed deterministic sample data for tests."""
        now = datetime.now(UTC)
        self.latest: dict[str, PrometheusSample | None] = {
            "md_throughput_mps": PrometheusSample(
                metric="md_throughput_mps",
                value=5400.0,
                timestamp=now,
            ),
            "md_failover_latency_ms": PrometheusSample(
                metric="md_failover_latency_ms",
                value=1800.0,
                timestamp=now,
            ),
            "md_runbook_exit_code": PrometheusSample(
                metric="md_runbook_exit_code",
                value=0.0,
                timestamp=now,
            ),
            "consumer_backlog_messages": PrometheusSample(
                metric="consumer_backlog_messages",
                value=12.0,
                timestamp=now,
            ),
        }
        self.range_samples: list[PrometheusSample] = [
            PrometheusSample(metric="md_throughput_mps", value=5000.0, timestamp=now),
            PrometheusSample(metric="md_throughput_mps", value=5200.0, timestamp=now),
        ]

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
        return self.latest.get(key)

    async def query_latest(self, metric: str) -> PrometheusSample | None:
        return self._resolve(metric)

    async def query_range(
        self, metric: str, *, minutes: int, step_seconds: int = 60
    ) -> list[PrometheusSample]:
        _ = (metric, minutes, step_seconds)
        return self.range_samples


@pytest.mark.asyncio
async def test_execute_caches_repeat_requests() -> None:
    repo = InMemoryStatusRepository()
    runbook = StubRunbookExecutor()
    service = OperationsConsoleService(
        runbook_executor=runbook,
        health_executor=StubHealthExecutor(),
        status_repository=repo,
        prometheus_client=StubPrometheusClient(),
    )
    request = RunbookRequest(
        command=RunbookCommand.START, mode="mock", request_id="req-1"
    )
    first = await service.execute(request)
    second = await service.execute(request)
    assert first.runbook.request_id == second.runbook.request_id
    assert len(runbook.calls) == 1


@pytest.mark.asyncio
async def test_execute_health_check_updates_repository() -> None:
    repo = InMemoryStatusRepository()
    service = OperationsConsoleService(
        runbook_executor=StubRunbookExecutor(),
        health_executor=StubHealthExecutor(),
        status_repository=repo,
        prometheus_client=StubPrometheusClient(),
    )
    request = RunbookRequest(command=RunbookCommand.HEALTH_CHECK, mode="mock")
    envelope = await service.execute(request)
    state = await repo.load()
    assert envelope.health is not None
    assert state.last_health is not None
    assert state.executions_by_request[envelope.runbook.request_id] == envelope.runbook


@pytest.mark.asyncio
async def test_metrics_summary_combines_health_and_prometheus() -> None:
    repo = InMemoryStatusRepository()
    runbook = StubRunbookExecutor()
    health = StubHealthExecutor()
    prom = StubPrometheusClient()
    service = OperationsConsoleService(
        runbook_executor=runbook,
        health_executor=health,
        status_repository=repo,
        prometheus_client=prom,
    )
    await service.execute(
        RunbookRequest(command=RunbookCommand.HEALTH_CHECK, mode="mock")
    )
    summary = await service.get_metrics_summary()
    assert summary.coverage_ratio.metric == "md_subscription_coverage_ratio"
    assert summary.throughput_mps.value == pytest.approx(5400.0)
    assert summary.consumer_backlog_messages.value == 12.0


@pytest.mark.asyncio
async def test_get_timeseries_returns_points() -> None:
    repo = InMemoryStatusRepository()
    service = OperationsConsoleService(
        runbook_executor=StubRunbookExecutor(),
        health_executor=StubHealthExecutor(),
        status_repository=repo,
        prometheus_client=StubPrometheusClient(),
    )
    series = await service.get_timeseries("md_throughput_mps", minutes=5)
    assert [point.value for point in series.points] == [5000.0, 5200.0]


@pytest.mark.asyncio
async def test_metrics_summary_handles_missing_prometheus() -> None:
    repo = InMemoryStatusRepository()
    service = OperationsConsoleService(
        runbook_executor=StubRunbookExecutor(),
        health_executor=StubHealthExecutor(),
        status_repository=repo,
        prometheus_client=None,
    )
    await service.execute(
        RunbookRequest(command=RunbookCommand.HEALTH_CHECK, mode="mock")
    )
    summary = await service.get_metrics_summary()
    assert summary.throughput_mps.value is None
    assert summary.failover_latency_ms.value is None
    assert summary.runbook_exit_code.value is None
    assert summary.throughput_mps.stale is True


@pytest.mark.asyncio
async def test_execute_updates_active_profile_for_failover() -> None:
    repo = InMemoryStatusRepository()
    service = OperationsConsoleService(
        runbook_executor=StubRunbookExecutor(),
        health_executor=StubHealthExecutor(),
        status_repository=repo,
        prometheus_client=None,
    )
    request = RunbookRequest(command=RunbookCommand.FAILOVER, mode="live")
    await service.execute(request)
    state = await repo.load()
    assert state.active_profile == "backup"


def test_operations_status_state_trims_history() -> None:
    state = OperationsStatusState()
    now = datetime.now(CHINA_TZ)
    for index in range(RUNBOOK_HISTORY_LIMIT * 2 + 5):
        execution = RunbookExecution(
            request_id=f"req-{index}",
            command=RunbookCommand.START,
            mode="live",
            window="day",
            profile="live",
            config="primary",
            exit_code=0,
            status="success",
            started_at=now,
            finished_at=now,
            duration_ms=0,
            logs=[],
            raw_output=[],
            metadata={},
        )
        state.cache_runbook(execution)
    assert len(state.runbook_history) == RUNBOOK_HISTORY_LIMIT
    assert len(state.executions_by_request) == RUNBOOK_HISTORY_LIMIT * 2

    for index in range(HEALTH_HISTORY_LIMIT + 5):
        snapshot = HealthSnapshot(
            request_id=f"health-{index}",
            mode="mock",
            generated_at=now,
            exit_code=0,
            coverage_ratio=0.99,
            expected_total=10,
            active_total=10,
            missing_contracts=[],
            stalled_contracts=[],
            warnings=[],
            errors=[],
            report={},
        )
        state.cache_health(snapshot)
    assert len(state.health_by_request) == HEALTH_HISTORY_LIMIT


def test_metric_from_health_handles_missing_snapshot() -> None:
    service = OperationsConsoleService(
        runbook_executor=StubRunbookExecutor(),
        health_executor=StubHealthExecutor(),
        status_repository=InMemoryStatusRepository(),
        prometheus_client=None,
    )
    metric = service._metric_from_health(  # noqa: SLF001
        None,
        datetime.now(CHINA_TZ),
    )
    assert metric.value is None
    assert metric.metric == "md_subscription_coverage_ratio"


@pytest.mark.asyncio
async def test_metric_from_prom_handles_null_sample() -> None:
    class NullProm(StubPrometheusClient):
        async def query_latest(self, metric: str) -> PrometheusSample | None:  # type: ignore[override]
            _ = metric
            return None

    repo = InMemoryStatusRepository()
    service = OperationsConsoleService(
        runbook_executor=StubRunbookExecutor(),
        health_executor=StubHealthExecutor(),
        status_repository=repo,
        prometheus_client=NullProm(),
    )
    metric = await service._metric_from_prom("md_throughput_mps", "mps")  # noqa: SLF001
    assert metric.value is None
    assert metric.unit == "mps"
    assert metric.stale is True


@pytest.mark.asyncio
async def test_metric_from_prom_returns_sample() -> None:
    class SampleProm(StubPrometheusClient):
        async def query_latest(self, metric: str) -> PrometheusSample | None:  # type: ignore[override]
            _ = metric
            return PrometheusSample(
                metric=metric, value=42.0, timestamp=datetime.now(UTC)
            )

    service = OperationsConsoleService(
        runbook_executor=StubRunbookExecutor(),
        health_executor=StubHealthExecutor(),
        status_repository=InMemoryStatusRepository(),
        prometheus_client=SampleProm(),
    )
    metric = await service._metric_from_prom("md_throughput_mps", "mps")  # noqa: SLF001
    assert metric.value == pytest.approx(42.0)
    assert metric.source == "prometheus"
    assert metric.stale is False


def test_metric_from_health_stale_flag() -> None:
    snapshot = HealthSnapshot(
        request_id="health",
        mode="mock",
        generated_at=datetime.now(CHINA_TZ).replace(year=2000),
        exit_code=0,
        coverage_ratio=0.5,
        expected_total=10,
        active_total=5,
        missing_contracts=[],
        stalled_contracts=[],
        warnings=[],
        errors=[],
        report={},
    )
    service = OperationsConsoleService(
        runbook_executor=StubRunbookExecutor(),
        health_executor=StubHealthExecutor(),
        status_repository=InMemoryStatusRepository(),
        prometheus_client=None,
    )
    metric = service._metric_from_health(  # noqa: SLF001
        snapshot, datetime.now(CHINA_TZ)
    )
    assert metric.stale is True


def test_runbook_executor_build_args_variants(tmp_path) -> None:
    executor = RunbookExecutor(
        script_path=tmp_path / "script.sh",
        log_dir=tmp_path,
    )
    request = RunbookRequest(
        command=RunbookCommand.FAILBACK,
        mode="mock",
        window="night",
        profile="backup",
        config="custom",
        dry_run=True,
    )
    args = executor._build_args(request)  # noqa: SLF001
    assert "--config" in args
    assert "--failback" in args
    assert "--mock" in args
    assert "--debug" in args


def test_try_parse_json_returns_none_for_nondict() -> None:
    assert _try_parse_json("[1,2,3]") is None


class FakeStdout:
    """Async iterator that yields predefined lines."""

    def __init__(self, lines: list[bytes]) -> None:
        """Store the scripted output lines."""
        self._lines = lines

    async def readline(self) -> bytes:
        if self._lines:
            return self._lines.pop(0)
        return b""


class FakeProcess:
    """Fake subprocess object used to simulate stdout streaming."""

    def __init__(self, lines: list[bytes], exit_code: int = 0) -> None:
        """Initialize fake stdout and exit code."""
        self.stdout = FakeStdout(lines)
        self._exit_code = exit_code

    async def wait(self) -> int:
        return self._exit_code


@pytest.mark.asyncio
async def test_runbook_executor_streams_and_parses_logs(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    lines = [b'{"message":"hello"}\n', b"plain text\n"]
    process = FakeProcess(lines.copy())

    async def fake_subprocess(*args: Any, **kwargs: Any) -> FakeProcess:
        _ = (args, kwargs)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subprocess)
    executor = RunbookExecutor(script_path=tmp_path / "script.sh", log_dir=tmp_path)
    request = RunbookRequest(
        command=RunbookCommand.START, mode="live", request_id="req-42"
    )
    result = await executor.execute(request)
    assert result.exit_code == 0
    assert result.logs == [{"message": "hello"}]
    assert any("plain text" in entry for entry in result.raw_output)


@pytest.mark.asyncio
async def test_runbook_executor_handles_spawn_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    async def failing_subprocess(*args: Any, **kwargs: Any) -> FakeProcess:
        _ = (args, kwargs)
        raise OSError("boom")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", failing_subprocess)
    executor = RunbookExecutor(script_path=tmp_path / "script.sh", log_dir=tmp_path)
    request = RunbookRequest(
        command=RunbookCommand.START, mode="mock", request_id="req-99"
    )
    result = await executor.execute(request)
    assert result.exit_code == 127
    assert any("runbook_spawn_failure" in entry["message"] for entry in result.logs)


@pytest.mark.asyncio
async def test_json_status_repository_round_trip(tmp_path) -> None:
    repo = JsonStatusRepository(tmp_path / "status.json")
    state = OperationsStatusState()
    state.environment_mode = "mock"
    await repo.save(state)
    loaded = await repo.load()
    assert loaded.environment_mode == "mock"


def test_try_parse_json_filters_invalid() -> None:
    assert _try_parse_json('{"ok": true}') == {"ok": True}
    assert _try_parse_json("not-json") is None
