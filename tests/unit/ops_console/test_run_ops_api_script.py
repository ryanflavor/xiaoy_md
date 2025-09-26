from __future__ import annotations

import os
from pathlib import Path
from unittest import mock

from scripts.operations import run_ops_api


def test_main_sets_defaults(monkeypatch, tmp_path):
    status_file = tmp_path / "ops" / "status.json"
    health_dir = status_file.parent

    monkeypatch.setenv("OPS_STATUS_FILE", str(status_file))
    monkeypatch.setenv("OPS_HEALTH_OUTPUT_DIR", str(health_dir))
    monkeypatch.delenv("OPS_API_TOKENS", raising=False)
    monkeypatch.delenv("OPS_PROMETHEUS_URL", raising=False)
    monkeypatch.delenv("OPS_RUNBOOK_SCRIPT", raising=False)

    with mock.patch.object(run_ops_api, "uvicorn") as uvicorn_mock:
        run_ops_api.main(["--host", "127.0.0.1", "--port", "9999"])

    assert uvicorn_mock.run.called is True
    (app_target,), kwargs = uvicorn_mock.run.call_args
    assert app_target == "src.infrastructure.http.ops_api:app"
    assert kwargs["host"] == "127.0.0.1"
    assert kwargs["port"] == 9999
    assert kwargs["backlog"] >= 64

    assert status_file.exists()
    assert Path(os.environ["OPS_RUNBOOK_SCRIPT"]).exists()
    assert os.environ["OPS_API_TOKENS"] == "local-dev-ops-token"
    assert os.environ["OPS_PROMETHEUS_URL"]
