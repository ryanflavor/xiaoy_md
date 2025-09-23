"""FastAPI application exposing operations console endpoints."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, status

from src.application.ops_console import (
    ExecutionEnvelope,
    HealthCheckExecutor,
    JsonStatusRepository,
    MetricsSummary,
    OperationsConsoleService,
    OperationsStatusState,
    RunbookExecutor,
    RunbookRequest,
    TimeseriesSeries,
)
from src.application.prometheus_client import PrometheusClient
from src.config import AppSettings, get_settings


class RunbookExecuteResponse(ExecutionEnvelope):
    """API response payload for command execution."""


class StatusResponseModel(OperationsStatusState):
    """Status response tailored for UI consumption."""


def create_app(
    settings: AppSettings | None = None,
    *,
    service: OperationsConsoleService | None = None,
    allowed_tokens: set[str] | None = None,
) -> FastAPI:
    """Create a FastAPI app with the operations console bindings."""
    resolved_settings = settings or get_settings()
    if service is None:
        runbook_executor = RunbookExecutor(
            resolved_settings.ops_runbook_script,
            log_dir=resolved_settings.ops_health_output_dir,
        )
        health_executor = HealthCheckExecutor(
            output_dir=resolved_settings.ops_health_output_dir,
        )
        status_repository = JsonStatusRepository(resolved_settings.ops_status_file)
        prometheus = PrometheusClient(
            resolved_settings.ops_prometheus_base_url,
            timeout=resolved_settings.ops_prometheus_timeout_seconds,
        )
        service = OperationsConsoleService(
            runbook_executor=runbook_executor,
            health_executor=health_executor,
            status_repository=status_repository,
            prometheus_client=prometheus,
        )

    if service is None:  # pragma: no cover - defensive (should not happen)
        msg = "OperationsConsoleService failed to initialize"
        raise RuntimeError(msg)

    token_set = allowed_tokens or set(resolved_settings.ops_api_tokens)

    app = FastAPI(
        title="Operations Console API",
        version=resolved_settings.app_version,
        description="Automation and telemetry endpoints for the ops console",
    )

    def get_service() -> OperationsConsoleService:
        return service

    def get_tokens() -> set[str]:  # pragma: no cover - trivial accessor
        return token_set

    token_dep = Annotated[set[str], Depends(get_tokens)]
    service_dep = Annotated[OperationsConsoleService, Depends(get_service)]

    async def require_token(
        allowed_tokens: token_dep,
        authorization: Annotated[str | None, Header()] = None,
    ) -> str:
        if not allowed_tokens:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Operations API authentication not configured",
            )
        if not authorization:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing Authorization header",
            )
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authorization scheme",
            )
        if token not in allowed_tokens:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Unauthorized",
            )
        return token

    @app.post(
        "/api/ops/runbooks/execute",
        response_model=RunbookExecuteResponse,
        tags=["runbooks"],
    )
    async def execute_runbook(
        payload: RunbookRequest,
        _token: Annotated[str, Depends(require_token)],
        svc: service_dep,
    ) -> RunbookExecuteResponse:
        envelope = await svc.execute(payload)
        return RunbookExecuteResponse(**envelope.model_dump())

    @app.get(
        "/api/ops/status",
        response_model=StatusResponseModel,
        tags=["status"],
    )
    async def get_status(
        _token: Annotated[str, Depends(require_token)],
        svc: service_dep,
    ) -> StatusResponseModel:
        state = await svc.get_status()
        recent = state.runbook_history[-10:]
        response = state.model_copy(update={"runbook_history": recent})
        return StatusResponseModel(**response.model_dump())

    @app.get(
        "/api/ops/metrics/summary",
        response_model=MetricsSummary,
        tags=["metrics"],
    )
    async def get_metrics_summary(
        _: str = Depends(require_token),
        svc: OperationsConsoleService = Depends(get_service),  # noqa: B008
    ) -> MetricsSummary:
        return await svc.get_metrics_summary()

    @app.get(
        "/api/ops/metrics/timeseries",
        response_model=TimeseriesSeries,
        tags=["metrics"],
    )
    async def get_timeseries(
        metric: str,
        *,
        minutes: int = 60,
        step_seconds: int = 60,
        _token: Annotated[str, Depends(require_token)],
        svc: service_dep,
    ) -> TimeseriesSeries:
        return await svc.get_timeseries(
            metric, minutes=minutes, step_seconds=step_seconds
        )

    return app


@lru_cache(maxsize=1)
def app() -> FastAPI:
    """Lazily instantiated FastAPI app for ASGI servers."""
    return create_app()
