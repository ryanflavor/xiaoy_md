"""Utility entrypoint to launch the operations FastAPI server."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

import uvicorn

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 9180
DEFAULT_PROM_URL = "http://prometheus:9090"
DEFAULT_RUNBOOK_SCRIPT = "scripts/operations/start_live_env.sh"
DEFAULT_STATUS_FILENAME = "ops_console_status.json"


def main(argv: list[str] | None = None) -> None:
    """Parse arguments, normalise environment defaults, and launch uvicorn."""
    parser = argparse.ArgumentParser(description="Run the operations API server")
    parser.add_argument(
        "--host", default=None, help="Bind host (overrides OPS_API_HOST)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Bind port (overrides OPS_API_PORT)",
    )
    args = parser.parse_args(argv)

    host = args.host or os.getenv("OPS_API_HOST", DEFAULT_HOST)
    port_raw = args.port or os.getenv("OPS_API_PORT")

    try:
        port = int(port_raw) if port_raw is not None else DEFAULT_PORT
    except ValueError as exc:  # pragma: no cover - defensive guard
        msg = f"Invalid port value for OPS_API_PORT: {port_raw!r}"
        raise SystemExit(msg) from exc

    _ensure_runtime_defaults()

    uvicorn.run(  # pragma: no cover - exercised in integration tests
        "src.infrastructure.http.ops_api:app",
        host=host,
        port=port,
        backlog=_resolve_backlog(),
    )


def _ensure_runtime_defaults() -> None:
    """Guarantee required directories and environment defaults exist."""
    status_path = _normalise_path(
        os.getenv("OPS_STATUS_FILE"),
        default=_health_dir() / DEFAULT_STATUS_FILENAME,
    )
    health_dir = status_path.parent
    runbook_script = _normalise_path(
        os.getenv("OPS_RUNBOOK_SCRIPT"), DEFAULT_RUNBOOK_SCRIPT
    )

    health_dir.mkdir(parents=True, exist_ok=True)
    if not status_path.exists():
        status_path.touch()

    os.environ.setdefault("OPS_STATUS_FILE", str(status_path))
    os.environ.setdefault("OPS_HEALTH_OUTPUT_DIR", str(health_dir))
    os.environ.setdefault("OPS_RUNBOOK_SCRIPT", str(runbook_script))
    os.environ.setdefault("OPS_PROMETHEUS_URL", DEFAULT_PROM_URL)

    if not os.getenv("OPS_API_TOKENS"):
        os.environ.setdefault("OPS_API_TOKENS", "local-dev-ops-token")
    os.environ.setdefault(
        "OPS_API_CORS_ORIGINS",
        "http://localhost:5173,http://localhost:5174,http://192.168.10.206:5173,http://192.168.10.206:5174",
    )
    os.environ.setdefault("OPS_API_CORS_METHODS", "GET,POST,OPTIONS")


def _health_dir() -> Path:
    raw = os.getenv("OPS_HEALTH_OUTPUT_DIR")
    return _normalise_path(raw, "logs/runbooks")


def _normalise_path(raw: str | None, default: Any) -> Path:
    """Return a resolved Path from environment or default."""
    base = Path(raw or default)
    return base.expanduser().resolve()


def _resolve_backlog() -> int:
    """Derive uvicorn backlog from environment when provided."""
    value = os.getenv("OPS_API_BACKLOG")
    if value is None:
        return 2048
    try:
        parsed = int(value)
    except ValueError:  # pragma: no cover - defensive guard
        return 2048
    return max(64, parsed)


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    main()
