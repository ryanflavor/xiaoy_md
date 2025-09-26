"""FastAPI application exposing operations console endpoints."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware

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
    health_dir = Path(resolved_settings.ops_health_output_dir)
    health_dir.mkdir(parents=True, exist_ok=True)
    status_file = Path(resolved_settings.ops_status_file)
    status_file.parent.mkdir(parents=True, exist_ok=True)
    if not status_file.exists() or status_file.stat().st_size == 0:
        status_file.write_text(
            OperationsStatusState().model_dump_json(indent=2), encoding="utf-8"
        )

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

    cors_origins = list(resolved_settings.ops_api_cors_origins)

    allow_origins = cors_origins or ["*"]
    if any(origin == "*" for origin in allow_origins):
        allow_origins = ["*"]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def get_service() -> OperationsConsoleService:
        return service

    def get_tokens() -> set[str]:  # pragma: no cover - trivial accessor
        return token_set

    async def require_token(
        request: Request,
        authorization: Annotated[str | None, Header()] = None,
    ) -> str:
        if request.method == "OPTIONS":  # Allow CORS preflight without auth
            return "preflight"
        allowed_tokens = token_set
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
            import logging

            logging.getLogger(__name__).warning(
                "Unauthorized token access", extra={"provided_token": token}
            )
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
        _token: str = Depends(require_token),
        svc: OperationsConsoleService = Depends(get_service),  # noqa: B008
    ) -> RunbookExecuteResponse:
        envelope = await svc.execute(payload)
        return RunbookExecuteResponse(**envelope.model_dump())

    @app.get(
        "/api/ops/status",
        response_model=StatusResponseModel,
        tags=["status"],
    )
    async def get_status(
        _token: str = Depends(require_token),
        svc: OperationsConsoleService = Depends(get_service),  # noqa: B008
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
        _token: str = Depends(require_token),
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
        _token: str = Depends(require_token),
        svc: OperationsConsoleService = Depends(get_service),  # noqa: B008
    ) -> TimeseriesSeries:
        return await svc.get_timeseries(
            metric, minutes=minutes, step_seconds=step_seconds
        )

    return app


@lru_cache(maxsize=1)
def app() -> FastAPI:
    """Lazily instantiated FastAPI app for ASGI servers."""
    return create_app()
