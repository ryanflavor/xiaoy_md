"""Global Pytest fixtures for environment sanitization."""

from __future__ import annotations

import os

import pytest

_ENV_PREFIXES = (
    "CTP_",
    "NATS_",
    "RATE_LIMIT",
    "SUBSCRIBE_RATE_LIMIT",
    "SESSION_",
    "PUSHGATEWAY",
    "ACTIVE_",
)


@pytest.fixture(autouse=True)
def _clear_trading_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove residual trading env vars between tests (prevents cross-contamination)."""
    for key in list(os.environ):
        if key.startswith(_ENV_PREFIXES):
            monkeypatch.delenv(key, raising=False)
