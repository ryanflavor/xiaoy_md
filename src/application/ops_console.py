"""Application-layer services for the operations console command APIs."""

from __future__ import annotations

import asyncio
import asyncio.subprocess
from datetime import datetime
from enum import Enum
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol
from uuid import uuid4
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from src.application.prometheus_client import PrometheusSample


class PrometheusClientProtocol(Protocol):
    """Contract for Prometheus clients used by the console service."""

    async def query_latest(self, metric: str) -> PrometheusSample | None:
        """Return the most recent sample for a metric."""

    async def query_range(
        self,
        metric: str,
        *,
        minutes: int,
        step_seconds: int = 60,
    ) -> list[PrometheusSample]:
        """Return samples for a metric within a lookback window."""


CHINA_TZ = ZoneInfo("Asia/Shanghai")
RUNBOOK_HISTORY_LIMIT = 40
HEALTH_HISTORY_LIMIT = 20
HEALTH_STALE_THRESHOLD_SECONDS = 300


class RunbookCommand(str, Enum):
    """Supported automation command identifiers."""

    START = "start"
    STOP = "stop"
    RESTART = "restart"
    FAILOVER = "failover"
    FAILBACK = "failback"
    DRILL = "drill"
    HEALTH_CHECK = "health_check"


class RunbookRequest(BaseModel):
    """Normalized request payload for executing runbook commands."""

    model_config = ConfigDict(str_strip_whitespace=True)

    command: RunbookCommand
    mode: str = Field(default="live", pattern="^(live|mock)$")
    window: str = Field(default="day", pattern="^(day|night)$")
    profile: str = Field(default="live", min_length=1)
    config: str | None = Field(default=None)
    request_id: str | None = Field(default=None, max_length=64)
    reason: str | None = Field(default=None, max_length=280)
    enforce: bool = Field(
        default=False, description="Enforce remediation during health check"
    )
    dry_run: bool = Field(
        default=False, description="Request dry-run confirmation where available"
    )
    confirmation_token: str | None = Field(default=None, max_length=128)

    def ensure_request_id(self) -> RunbookRequest:
        """Return a copy with a generated request identifier when missing."""
        if self.request_id:
            return self
        return self.model_copy(update={"request_id": uuid4().hex})

    def normalized_config(self) -> str:
        """Return the effective configuration (primary/backup)."""
        if self.command == RunbookCommand.FAILOVER:
            return "backup"
        if self.command == RunbookCommand.FAILBACK:
            return "primary"
        return (self.config or "primary").lower()


class RunbookExecution(BaseModel):
    """Execution details for a runbook automation command."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    request_id: str
    command: RunbookCommand
    mode: str
    window: str
    profile: str
    config: str | None
    exit_code: int
    status: str
    started_at: datetime
    finished_at: datetime
    duration_ms: int
    logs: list[dict[str, Any]] = Field(default_factory=list)
    raw_output: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class HealthCheckExecution(BaseModel):
    """Execution details for a subscription health check."""

    request_id: str
    mode: str
    started_at: datetime
    finished_at: datetime
    exit_code: int
    report: dict[str, Any]
    raw_output: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_snapshot(self) -> HealthSnapshot:
        """Convert execution result to a snapshot suitable for status reporting."""
        payload = self.report
        coverage = _safe_float(payload.get("coverage_ratio"))
        expected = _safe_int(payload.get("expected_total"))
        active = _safe_int(payload.get("active_total"))
        missing: list[str] = list(payload.get("missing_contracts") or [])
        stalled_raw = payload.get("stalled_contracts") or []
        stalled = [dict(item) for item in stalled_raw if isinstance(item, dict)]
        warnings = list(payload.get("warnings") or [])
        errors = list(payload.get("errors") or [])
        generated_raw = payload.get("generated_at")
        generated_at = (
            datetime.fromisoformat(str(generated_raw))
            if generated_raw
            else self.finished_at
        )
        if generated_at.tzinfo is None:
            generated_at = generated_at.replace(tzinfo=CHINA_TZ)
        else:
            generated_at = generated_at.astimezone(CHINA_TZ)
        return HealthSnapshot(
            request_id=self.request_id,
            mode=self.mode,
            generated_at=generated_at,
            exit_code=self.exit_code,
            coverage_ratio=coverage,
            expected_total=expected,
            active_total=active,
            missing_contracts=missing,
            stalled_contracts=stalled,
            warnings=warnings,
            errors=errors,
            report=payload,
        )

    def to_runbook_execution(self, request: RunbookRequest) -> RunbookExecution:
        """Represent the health check as a runbook execution record."""
        duration_ms = max(
            0,
            int((self.finished_at - self.started_at).total_seconds() * 1000),
        )
        serialized_report = json.dumps(self.report, ensure_ascii=False, sort_keys=True)
        metadata = {
            "reason": request.reason,
            "enforce": request.enforce,
            "dry_run": request.dry_run,
            "confirmation_token": request.confirmation_token,
        }
        return RunbookExecution(
            request_id=self.request_id,
            command=RunbookCommand.HEALTH_CHECK,
            mode=self.mode,
            window=request.window,
            profile=request.profile,
            config=request.normalized_config(),
            exit_code=self.exit_code,
            status="success" if self.exit_code == 0 else "failed",
            started_at=self.started_at,
            finished_at=self.finished_at,
            duration_ms=duration_ms,
            logs=[],
            raw_output=[serialized_report],
            metadata={k: v for k, v in metadata.items() if v is not None},
        )


class HealthSnapshot(BaseModel):
    """Summary view of the latest health check outcome."""

    request_id: str
    mode: str
    generated_at: datetime
    exit_code: int
    coverage_ratio: float | None
    expected_total: int | None
    active_total: int | None
    missing_contracts: list[str] = Field(default_factory=list)
    stalled_contracts: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    report: dict[str, Any] = Field(default_factory=dict)


class OperationsStatusState(BaseModel):
    """Persistent status cache for operations console consumers."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    environment_mode: str = "unknown"
    active_profile: str = "primary"
    active_window: str = "day"
    last_runbook: RunbookExecution | None = None
    runbook_history: list[RunbookExecution] = Field(default_factory=list)
    executions_by_request: dict[str, RunbookExecution] = Field(default_factory=dict)
    health_by_request: dict[str, HealthSnapshot] = Field(default_factory=dict)
    last_health: HealthSnapshot | None = None
    last_exit_codes: dict[str, int] = Field(default_factory=dict)
    last_updated_at: datetime = Field(default_factory=lambda: datetime.now(CHINA_TZ))

    def append_runbook(self, execution: RunbookExecution) -> None:
        """Append a runbook execution to history with trimming."""
        self.runbook_history.append(execution)
        if len(self.runbook_history) > RUNBOOK_HISTORY_LIMIT:
            self.runbook_history = self.runbook_history[-RUNBOOK_HISTORY_LIMIT:]

    def cache_runbook(self, execution: RunbookExecution) -> None:
        """Cache execution by request identifier and maintain history."""
        self.executions_by_request[execution.request_id] = execution
        if len(self.executions_by_request) > RUNBOOK_HISTORY_LIMIT * 2:
            keys = list(self.executions_by_request)[-RUNBOOK_HISTORY_LIMIT * 2 :]
            self.executions_by_request = {
                key: self.executions_by_request[key] for key in keys
            }
        self.append_runbook(execution)
        self.last_runbook = execution
        self.last_exit_codes[execution.command.value] = execution.exit_code
        self.last_updated_at = datetime.now(CHINA_TZ)

    def cache_health(self, snapshot: HealthSnapshot) -> None:
        """Record the latest health snapshot with trimming."""
        self.health_by_request[snapshot.request_id] = snapshot
        if len(self.health_by_request) > HEALTH_HISTORY_LIMIT:
            keys = list(self.health_by_request)[-HEALTH_HISTORY_LIMIT:]
            self.health_by_request = {key: self.health_by_request[key] for key in keys}
        self.last_health = snapshot
        self.last_exit_codes[RunbookCommand.HEALTH_CHECK.value] = snapshot.exit_code
        self.last_updated_at = datetime.now(CHINA_TZ)


class MetricPoint(BaseModel):
    """Single metric value with freshness metadata."""

    metric: str
    value: float | None
    unit: str | None = None
    updated_at: datetime | None = None
    stale: bool = True
    source: str | None = None


class MetricsSummary(BaseModel):
    """Aggregate metrics exposed to the operations console UI."""

    coverage_ratio: MetricPoint
    throughput_mps: MetricPoint
    failover_latency_ms: MetricPoint
    runbook_exit_code: MetricPoint
    consumer_backlog_messages: MetricPoint


class TimeseriesPoint(BaseModel):
    """Single data point for metric time series output."""

    timestamp: datetime
    value: float


class TimeseriesSeries(BaseModel):
    """Time series payload for a metric."""

    metric: str
    unit: str | None = None
    points: list[TimeseriesPoint] = Field(default_factory=list)


class RunbookExecutorProtocol(Protocol):
    """Protocol for runbook command execution backends."""

    async def execute(
        self, request: RunbookRequest
    ) -> RunbookExecution:  # pragma: no cover - interface
        """Execute the given runbook request."""


class HealthCheckExecutorProtocol(Protocol):
    """Protocol for health check execution backends."""

    async def run(
        self, request: RunbookRequest
    ) -> HealthCheckExecution:  # pragma: no cover - interface
        """Execute the health check for the given request."""


class StatusRepository(Protocol):
    """Protocol for status persistence."""

    async def load(self) -> OperationsStatusState:  # pragma: no cover - interface
        """Load status state from storage."""

    async def save(
        self, state: OperationsStatusState
    ) -> None:  # pragma: no cover - interface
        """Persist status state to storage."""


class RunbookExecutor(RunbookExecutorProtocol):
    """Shell-based executor that wraps start_live_env.sh."""

    def __init__(
        self,
        script_path: os.PathLike[str],
        *,
        log_dir: os.PathLike[str],
        env_overrides: dict[str, str] | None = None,
    ) -> None:
        """Initialize the shell-backed runbook executor."""
        self._script_path = os.fspath(script_path)
        self._log_dir = os.fspath(log_dir)
        self._env_overrides = dict(env_overrides or {})

    async def execute(self, request: RunbookRequest) -> RunbookExecution:
        request = request.ensure_request_id()
        started_at = datetime.now(CHINA_TZ)
        args = self._build_args(request)
        env = os.environ.copy()
        env.update(self._env_overrides)
        env.setdefault("TZ", "Asia/Shanghai")
        env.setdefault("LOG_DIR", self._log_dir)
        if request.mode == "mock":
            env["MOCK_MODE"] = "1"
            env.setdefault("ORCH_TEST_MODE", "mock")
        if request.reason:
            env["OPS_REASON"] = request.reason
        if request.confirmation_token:
            env["OPS_CONFIRMATION_TOKEN"] = request.confirmation_token
        raw_output: list[str] = []
        logs: list[dict[str, Any]] = []
        exit_code = -1
        try:
            process = await asyncio.create_subprocess_exec(
                "bash",
                self._script_path,
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
            )
            if process.stdout is None:  # pragma: no cover - defensive guard
                msg = "stdout pipe unavailable for runbook execution"
                raise RuntimeError(msg)
            async for line in _iterate_stream(process.stdout):
                raw_output.append(line)
                parsed = _try_parse_json(line)
                if parsed is not None:
                    logs.append(parsed)
            exit_code = await process.wait()
        except OSError as exc:
            exit_code = 127
            message = json.dumps(
                {
                    "timestamp": datetime.now(CHINA_TZ).isoformat(),
                    "level": "ERROR",
                    "message": "runbook_spawn_failure",
                    "error": str(exc),
                },
                ensure_ascii=False,
            )
            raw_output.append(message)
            logs.append(json.loads(message))
        finished_at = datetime.now(CHINA_TZ)
        duration_ms = max(0, int((finished_at - started_at).total_seconds() * 1000))
        metadata = {
            "reason": request.reason,
            "dry_run": request.dry_run,
            "enforce": request.enforce,
        }
        return RunbookExecution(
            request_id=request.request_id or uuid4().hex,
            command=request.command,
            mode=request.mode,
            window=request.window,
            profile=request.profile,
            config=request.normalized_config(),
            exit_code=exit_code,
            status="success" if exit_code == 0 else "failed",
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
            logs=logs,
            raw_output=raw_output,
            metadata={k: v for k, v in metadata.items() if v is not None},
        )

    def _build_args(self, request: RunbookRequest) -> list[str]:
        args = ["--window", request.window, "--profile", request.profile]
        config = request.normalized_config()
        if config:
            args.extend(["--config", config])
        args.extend(["--log-dir", self._log_dir])
        if request.command == RunbookCommand.RESTART:
            args.append("--restart")
        elif request.command == RunbookCommand.STOP:
            args.append("--stop")
        elif request.command == RunbookCommand.FAILOVER:
            args.append("--failover")
        elif request.command == RunbookCommand.FAILBACK:
            args.append("--failback")
        elif request.command == RunbookCommand.DRILL:
            args.append("--drill")
        if request.mode == "mock":
            args.append("--mock")
        if request.dry_run:
            args.append("--debug")  # enable verbose output for confirmation
        return args


class HealthCheckExecutor(HealthCheckExecutorProtocol):
    """Executor backed by check_feed_health automation."""

    def __init__(
        self,
        *,
        output_dir: os.PathLike[str],
        log_prefix: str = "subscription_health_ops_console",
    ) -> None:
        """Initialize the health check executor."""
        from src.operations.check_feed_health import async_main, build_parser

        self._output_dir = os.fspath(output_dir)
        self._log_prefix = log_prefix
        self._async_main = async_main
        self._build_parser = build_parser

    async def run(self, request: RunbookRequest) -> HealthCheckExecution:
        request = request.ensure_request_id()
        if request.mode == "mock":
            return self._mock_execution(request)
        started_at = datetime.now(CHINA_TZ)
        parser = self._build_parser()
        args = parser.parse_args(self._build_cli_args(request))
        report = await self._async_main(args)
        finished_at = datetime.now(CHINA_TZ)
        payload = report.to_dict()
        return HealthCheckExecution(
            request_id=request.request_id or uuid4().hex,
            mode=request.mode,
            started_at=started_at,
            finished_at=finished_at,
            exit_code=int(report.exit_code),
            report=payload,
            raw_output=[json.dumps(payload, ensure_ascii=False, sort_keys=True)],
            metadata={
                "reason": request.reason,
                "enforce": request.enforce,
                "dry_run": request.dry_run,
            },
        )

    def _build_cli_args(self, request: RunbookRequest) -> list[str]:
        args = [
            "--mode",
            "enforce" if request.enforce else "dry-run",
            "--session-window",
            request.window,
            "--out-dir",
            self._output_dir,
            "--log-prefix",
            self._log_prefix,
            "--json-indent",
            "2",
        ]
        if request.dry_run:
            args.extend(["--skip-metrics"])
        return args

    def _mock_execution(self, request: RunbookRequest) -> HealthCheckExecution:
        now = datetime.now(CHINA_TZ)
        report = {
            "generated_at": now.isoformat(),
            "mode": "mock",
            "coverage_ratio": 0.9985,
            "expected_total": 1280,
            "active_total": 1278,
            "matched_total": 1276,
            "missing_contracts": ["ag2412.SHFE", "cu2501.SHFE"],
            "unexpected_contracts": [],
            "stalled_contracts": [],
            "warnings": ["mock_mode"],
            "errors": [],
            "exit_code": 0,
        }
        return HealthCheckExecution(
            request_id=request.request_id or uuid4().hex,
            mode="mock",
            started_at=now,
            finished_at=now,
            exit_code=0,
            report=report,
            raw_output=[json.dumps(report, ensure_ascii=False, sort_keys=True)],
            metadata={"mock": True},
        )


class JsonStatusRepository(StatusRepository):
    """JSON-file backed status repository."""

    def __init__(self, path: os.PathLike[str]) -> None:
        """Create repository bound to a JSON status file."""
        self._path = os.fspath(path)
        self._lock = asyncio.Lock()

    async def load(self) -> OperationsStatusState:
        async with self._lock:
            try:
                data = await asyncio.to_thread(_read_text, self._path)
            except FileNotFoundError:
                return OperationsStatusState()
            payload = json.loads(data)
            return OperationsStatusState.model_validate(payload)

    async def save(self, state: OperationsStatusState) -> None:
        async with self._lock:
            payload = json.dumps(
                state.model_dump(mode="json"), ensure_ascii=False, indent=2
            )
            await asyncio.to_thread(_write_text, self._path, payload)


class OperationsConsoleService:
    """High-level coordination for operations console actions."""

    def __init__(
        self,
        *,
        runbook_executor: RunbookExecutorProtocol,
        health_executor: HealthCheckExecutorProtocol,
        status_repository: StatusRepository,
        prometheus_client: PrometheusClientProtocol | None = None,
    ) -> None:
        """Initialize the operations console coordinator."""
        self._runbook_executor = runbook_executor
        self._health_executor = health_executor
        self._repository = status_repository
        self._prometheus = prometheus_client

    async def execute(self, request: RunbookRequest) -> ExecutionEnvelope:
        request = request.ensure_request_id()
        state = await self._repository.load()
        request_id = request.request_id
        if request_id is None:  # pragma: no cover - safety guard for typing
            msg = "request_id missing after ensure_request_id"
            raise RuntimeError(msg)
        existing = state.executions_by_request.get(request_id)
        if existing is not None:
            health = state.health_by_request.get(request_id)
            return ExecutionEnvelope(runbook=existing, health=health)

        if request.command == RunbookCommand.HEALTH_CHECK:
            execution = await self._health_executor.run(request)
            runbook_record = execution.to_runbook_execution(request)
            health_snapshot = execution.to_snapshot()
            state.cache_runbook(runbook_record)
            state.cache_health(health_snapshot)
            await self._repository.save(state)
            return ExecutionEnvelope(runbook=runbook_record, health=health_snapshot)

        runbook_record = await self._runbook_executor.execute(request)
        state.cache_runbook(runbook_record)
        state.environment_mode = request.mode
        state.active_window = request.window
        self._update_active_profile(state, request, runbook_record)
        await self._repository.save(state)
        return ExecutionEnvelope(runbook=runbook_record, health=None)

    async def get_status(self) -> OperationsStatusState:
        """Return the cached status for the console."""
        return await self._repository.load()

    async def get_metrics_summary(self) -> MetricsSummary:
        """Aggregate key metrics for overview dashboards."""
        state = await self._repository.load()
        now = datetime.now(CHINA_TZ)
        coverage = self._metric_from_health(state.last_health, now)
        throughput = await self._metric_from_prom("md_throughput_mps", "mps")
        failover_latency = await self._metric_from_prom("md_failover_latency_ms", "ms")
        runbook_exit = await self._metric_from_prom("md_runbook_exit_code", None)
        backlog = await self._metric_from_prom("consumer_backlog_messages", "messages")
        return MetricsSummary(
            coverage_ratio=coverage,
            throughput_mps=throughput,
            failover_latency_ms=failover_latency,
            runbook_exit_code=runbook_exit,
            consumer_backlog_messages=backlog,
        )

    async def get_timeseries(
        self,
        metric: str,
        *,
        minutes: int,
        step_seconds: int = 60,
    ) -> TimeseriesSeries:
        """Fetch time-series data for the requested metric."""
        samples: list[PrometheusSample] = []
        if self._prometheus is not None:
            samples = await self._prometheus.query_range(
                metric, minutes=minutes, step_seconds=step_seconds
            )
        points = [
            TimeseriesPoint(timestamp=s.timestamp, value=s.value) for s in samples
        ]
        return TimeseriesSeries(metric=metric, unit=None, points=points)

    def _update_active_profile(
        self,
        state: OperationsStatusState,
        request: RunbookRequest,
        execution: RunbookExecution,
    ) -> None:
        if execution.command == RunbookCommand.FAILOVER:
            state.active_profile = "backup"
        elif execution.command == RunbookCommand.FAILBACK:
            state.active_profile = "primary"
        elif execution.command in {
            RunbookCommand.START,
            RunbookCommand.RESTART,
            RunbookCommand.DRILL,
        }:
            state.active_profile = request.normalized_config()

    def _metric_from_health(
        self, snapshot: HealthSnapshot | None, now: datetime
    ) -> MetricPoint:
        if snapshot is None:
            return MetricPoint(metric="md_subscription_coverage_ratio", value=None)
        age = (now - snapshot.generated_at).total_seconds()
        return MetricPoint(
            metric="md_subscription_coverage_ratio",
            value=snapshot.coverage_ratio,
            unit=None,
            updated_at=snapshot.generated_at,
            stale=age > HEALTH_STALE_THRESHOLD_SECONDS,
            source="health_report",
        )

    async def _metric_from_prom(self, metric: str, unit: str | None) -> MetricPoint:
        if self._prometheus is None:
            return MetricPoint(metric=metric, value=None, unit=unit)
        sample = await self._prometheus.query_latest(metric)
        if sample is None:
            return MetricPoint(metric=metric, value=None, unit=unit)
        return MetricPoint(
            metric=metric,
            value=sample.value,
            unit=unit,
            updated_at=sample.timestamp,
            stale=False,
            source="prometheus",
        )


class ExecutionEnvelope(BaseModel):
    """Response envelope that pairs runbook records with optional health snapshots."""

    runbook: RunbookExecution
    health: HealthSnapshot | None = None


async def _iterate_stream(stream: asyncio.StreamReader) -> AsyncIterator[str]:
    while True:
        line = await stream.readline()
        if not line:
            break
        yield line.decode("utf-8", errors="replace").rstrip()


def _try_parse_json(payload: str) -> dict[str, Any] | None:
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None
    if isinstance(data, dict):
        return data
    return None


def _read_text(path: os.PathLike[str] | str) -> str:
    return Path(path).read_text(encoding="utf-8")


def _write_text(path: os.PathLike[str] | str, data: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(data, encoding="utf-8")


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
