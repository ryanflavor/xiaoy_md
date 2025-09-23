"""CLI-focused tests for full_feed_subscription module."""

from __future__ import annotations

import argparse
import json
import logging
import os
from types import SimpleNamespace
from typing import TYPE_CHECKING

from nats import errors as nats_errors
from prometheus_client import CollectorRegistry
from prometheus_client.parser import text_string_to_metric_families
import pytest

from src.operations import full_feed_subscription as ffs

if TYPE_CHECKING:
    from pathlib import Path


def test_build_parser_accepts_window_and_config():
    parser = ffs.build_parser()
    args = parser.parse_args(
        [
            "--window",
            "night",
            "--config",
            "backup",
            "--metrics-host",
            "127.0.0.1",
            "--metrics-port",
            "9400",
        ]
    )

    assert args.window == "night"
    assert args.config == "backup"
    assert args.metrics_host == "127.0.0.1"
    assert args.metrics_port == 9400


def test_main_sets_session_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    env_file = tmp_path / "test.env"
    env_file.write_text("NATS_URL=nats://127.0.0.1:4222\n", encoding="utf-8")

    monkeypatch.delenv("SESSION_WINDOW", raising=False)
    monkeypatch.delenv("SESSION_CONFIG", raising=False)

    captured: dict[str, str] = {}

    async def fake_run_workflow(args, logger):  # type: ignore[override]
        captured["window"] = args.window
        captured["config"] = args.config
        # Ensure environment visible to downstream logic
        captured["env_window"] = os.environ.get("SESSION_WINDOW", "") or ""
        captured["env_config"] = os.environ.get("SESSION_CONFIG", "") or ""

    monkeypatch.setattr(ffs, "run_workflow", fake_run_workflow)

    result = ffs.main(
        [
            "--env-file",
            str(env_file),
            "--window",
            "night",
            "--config",
            "backup",
            "--dry-run",
            "--output-dir",
            str(tmp_path / "out"),
            "--nats-url",
            "nats://localhost:4222",
        ]
    )

    assert result == 0
    assert captured["window"] == "night"
    assert captured["config"] == "backup"
    assert captured["env_window"] == "night"
    assert captured["env_config"] == "backup"

    monkeypatch.delenv("SESSION_WINDOW", raising=False)
    monkeypatch.delenv("SESSION_CONFIG", raising=False)


def test_subscription_metrics_exporter_records_values():
    registry = CollectorRegistry()
    exporter = ffs.SubscriptionMetricsExporter(
        host="127.0.0.1",
        port=0,
        labels=ffs.SubscriptionMetricsLabels(
            feed="primary",
            account="acct",
            session_window="day",
        ),
        registry=registry,
        start_http=False,
    )

    exporter.observe_coverage(0.845)
    exporter.increment_rate_limit(3)

    metrics = exporter.scrape().decode("utf-8")
    families = {
        family.name: family for family in text_string_to_metric_families(metrics)
    }

    coverage_sample = families["md_subscription_coverage_ratio"].samples[0]
    assert coverage_sample.labels["feed"] == "primary"
    assert coverage_sample.labels["account"] == "acct"
    assert coverage_sample.labels["session_window"] == "day"
    assert coverage_sample.value == pytest.approx(0.845, rel=1e-3)

    rate_limit_sample = families["md_rate_limit_hits"].samples[0]
    assert rate_limit_sample.value == 3.0


@pytest.mark.asyncio
async def test_request_json_retries_when_no_responders():
    attempts: list[int] = []

    class DummyNC:
        async def request(self, subject, payload, timeout):
            _ = (subject, payload, timeout)
            attempts.append(1)
            if len(attempts) == 1:
                raise nats_errors.NoRespondersError
            return SimpleNamespace(data=json.dumps({"ok": True}).encode("utf-8"))

    result = await ffs._request_json(  # noqa: SLF001 - exercising internal helper
        DummyNC(),
        "subject",
        {"foo": "bar"},
        timeout=0.1,
        max_attempts=3,
        retry_delay=0,
        logger=None,
    )

    assert result == {"ok": True}
    assert len(attempts) == 2


@pytest.mark.asyncio
async def test_request_json_raises_after_retry_exhausted():
    attempt_count = 0

    class DummyNC:
        async def request(self, subject, payload, timeout):
            _ = (subject, payload, timeout)
            nonlocal attempt_count
            attempt_count += 1
            raise nats_errors.NoRespondersError

    with pytest.raises(nats_errors.NoRespondersError) as exc_info:
        await ffs._request_json(  # noqa: SLF001 - exercising internal helper
            DummyNC(),
            "subject",
            {"foo": "bar"},
            timeout=0.1,
            max_attempts=2,
            retry_delay=0,
            logger=None,
        )

    assert isinstance(exc_info.value, nats_errors.NoRespondersError)
    assert attempt_count == 2


@pytest.mark.asyncio
async def test_request_json_retries_on_timeout():
    attempts = 0

    class DummyNC:
        async def request(self, subject, payload, timeout):
            _ = (subject, payload, timeout)
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise nats_errors.TimeoutError
            return SimpleNamespace(data=json.dumps({"ok": True}).encode("utf-8"))

    result = await ffs._request_json(  # noqa: SLF001 - exercising internal helper
        DummyNC(),
        "subject",
        {"foo": "bar"},
        timeout=0.1,
        max_attempts=3,
        retry_delay=0,
        logger=None,
    )

    assert result == {"ok": True}
    assert attempts == 2


@pytest.mark.asyncio
async def test_request_json_timeout_after_retry_exhausted():
    attempts = 0

    class DummyNC:
        async def request(self, subject, payload, timeout):
            _ = (subject, payload, timeout)
            nonlocal attempts
            attempts += 1
            raise nats_errors.TimeoutError

    with pytest.raises(nats_errors.TimeoutError):
        await ffs._request_json(  # noqa: SLF001 - exercising internal helper
            DummyNC(),
            "subject",
            {"foo": "bar"},
            timeout=0.1,
            max_attempts=2,
            retry_delay=0,
            logger=None,
        )

    assert attempts == 2


@pytest.mark.asyncio
async def test_run_workflow_reduces_batch_after_timeout(monkeypatch, tmp_path):
    async def fake_fetch_contracts(_nc, _timeout, **_kwargs):
        return {"symbols": ["S1", "S2", "S3", "S4"], "source": "test"}

    calls: list[list[str]] = []

    from nats import errors as nats_errors

    async def fake_bulk_subscribe(_nc, symbols, _timeout, **_kwargs):
        calls.append(list(symbols))
        if len(symbols) > 1:
            raise nats_errors.TimeoutError
        return {"accepted": list(symbols), "rejected": []}

    class DummyNATS:
        async def connect(self, **_):
            return None

        async def close(self):
            return None

    async def noop_acquire(self, _count):
        return None

    monkeypatch.setattr(ffs, "_fetch_contracts", fake_fetch_contracts)
    monkeypatch.setattr(ffs, "_bulk_subscribe", fake_bulk_subscribe)

    async def fake_fetch_active(_nc, _timeout, **_kwargs):
        return set(), False

    monkeypatch.setattr(ffs, "_fetch_active_subscriptions", fake_fetch_active)
    from nats.aio import client as nats_client_module

    monkeypatch.setattr(nats_client_module, "Client", DummyNATS)
    monkeypatch.setattr(ffs.RateLimiter, "acquire", noop_acquire)

    args = argparse.Namespace(
        env_file=".env",  # unused in test
        nats_url="nats://localhost:4222",
        user="user",
        password="pass",  # pragma: allowlist secret
        contracts_timeout=1.0,
        subscribe_timeout=0.1,
        batch_size=4,
        limit=None,
        include=None,
        exclude=None,
        output_dir=str(tmp_path),
        rate_limit_max=0,
        rate_limit_window=0,
        rate_limit_retry_delay=0.0,
        max_retries=0,
        allow_ampersand=True,
        dry_run=False,
        verbose=False,
        window="day",
        config="primary",
        metrics_host="127.0.0.1",
        metrics_port=0,
        metrics_disable=True,
        nats_request_attempts=1,
        nats_request_retry_delay=0.0,
    )

    logger = logging.getLogger("test")
    summary = await ffs.run_workflow(args, logger)

    assert len(summary.accepted_symbols) == 4
    assert any(len(call) == 1 for call in calls)
