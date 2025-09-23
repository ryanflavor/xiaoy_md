"""Unit tests for subscription health check orchestration."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import json
import sys
import types
from typing import TYPE_CHECKING

import pytest

from src.operations import check_feed_health as health

if TYPE_CHECKING:
    from pathlib import Path

CHINA_TZ = health.CHINA_TZ


def make_record(
    symbol: str,
    *,
    last_tick_delta: timedelta | None = timedelta(0),
    active: bool = True,
    missing_last_tick: bool = False,
) -> health.SubscriptionRecord:
    now = datetime.now(CHINA_TZ)
    if missing_last_tick:
        last_tick = None
    else:
        delta = last_tick_delta or timedelta(0)
        last_tick = now - delta
    return health.SubscriptionRecord(
        symbol=symbol,
        subscription_id=f"sub-{symbol}",
        created_at=now,
        last_tick_at=last_tick,
        active=active,
        exchange=symbol.split(".")[-1] if "." in symbol else "SHFE",
    )


def test_evaluate_health_success() -> None:
    expected = {"rb2401.SHFE", "IF2312.CFFEX"}
    records = [
        make_record("rb2401.SHFE"),
        make_record("IF2312.CFFEX"),
    ]

    config = health.HealthEvaluationConfig(
        coverage_threshold=0.99,
        warning_lag=120.0,
        critical_lag=300.0,
        mode="dry-run",
    )
    report = health.evaluate_health(expected, records, config=config)

    assert report.exit_code == health.EXIT_SUCCESS
    assert not report.missing_contracts
    assert not report.stalled_contracts
    assert report.coverage_ratio == pytest.approx(1.0)


def test_evaluate_health_missing_contract_triggers_error() -> None:
    expected = {"rb2401.SHFE", "IF2312.CFFEX"}
    records = [make_record("rb2401.SHFE")]

    config = health.HealthEvaluationConfig(
        coverage_threshold=0.99,
        warning_lag=120.0,
        critical_lag=300.0,
        mode="dry-run",
    )
    report = health.evaluate_health(expected, records, config=config)

    assert report.exit_code == health.EXIT_ERROR
    assert report.missing_contracts == ["IF2312.CFFEX"]
    assert any("Missing" in msg for msg in report.errors)


def test_evaluate_health_stalled_warning_vs_critical() -> None:
    expected = {"rb2401.SHFE"}
    warn_delta = timedelta(seconds=150)
    crit_delta = timedelta(seconds=400)

    warning_record = make_record("rb2401.SHFE", last_tick_delta=warn_delta)
    critical_record = make_record("au2501.SHFE", last_tick_delta=crit_delta)
    records = [warning_record, critical_record]

    config = health.HealthEvaluationConfig(
        coverage_threshold=0.5,
        warning_lag=120.0,
        critical_lag=300.0,
        mode="dry-run",
    )
    report = health.evaluate_health(expected, records, config=config)

    assert report.exit_code == health.EXIT_ERROR
    stalled_symbols = {item.symbol: item.severity for item in report.stalled_contracts}
    assert stalled_symbols["rb2401.SHFE"] == "warning"
    assert stalled_symbols["au2501.SHFE"] == "critical"
    assert any("critical" in msg for msg in report.errors)
    assert any("warning" in msg for msg in report.warnings)


@pytest.mark.asyncio
async def test_run_health_check_offline(tmp_path: Path) -> None:
    catalogue = tmp_path / "contracts.json"
    active_snapshot = tmp_path / "active.json"

    catalogue.write_text(
        json.dumps({"symbols": ["rb2401.SHFE", "IF2312.CFFEX"]}),
        encoding="utf-8",
    )
    future_tick = "2999-01-01T00:00:00+08:00"
    snapshot_payload = {
        "subscriptions": [
            {
                "symbol": "rb2401.SHFE",
                "subscription_id": "sub-1",
                "exchange": "SHFE",
                "created_at": "2025-01-01T09:00:00+08:00",
                "last_tick_at": future_tick,
                "active": True,
            },
            {
                "symbol": "IF2312.CFFEX",
                "subscription_id": "sub-2",
                "exchange": "CFFEX",
                "created_at": "2025-01-01T09:00:00+08:00",
                "last_tick_at": future_tick,
                "active": True,
            },
        ]
    }
    active_snapshot.write_text(
        json.dumps(snapshot_payload),
        encoding="utf-8",
    )

    parser = health.build_parser()
    args = parser.parse_args(
        [
            "--catalogue",
            str(catalogue),
            "--active-file",
            str(active_snapshot),
            "--skip-metrics",
            "--out-dir",
            str(tmp_path / "out"),
        ]
    )

    logger = health.configure_logging(None)
    report = await health.run_health_check(args, logger)

    assert report.exit_code == health.EXIT_SUCCESS
    assert report.coverage_ratio == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_run_health_check_enforce_invokes_remediation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    parser = health.build_parser()
    args = parser.parse_args(
        [
            "--mode",
            "enforce",
            "--skip-metrics",
            "--out-dir",
            str(tmp_path / "out"),
        ]
    )

    async def fake_expected(_args, _logger):
        return {"rb2401.SHFE"}, {"source": "fixture"}

    snapshots = [
        (
            [
                health.SubscriptionRecord(
                    symbol="IF2312.CFFEX",
                    subscription_id="sub-if",
                    created_at=datetime.now(CHINA_TZ),
                    last_tick_at=datetime.now(CHINA_TZ),
                    active=True,
                )
            ],
            {"source": "fixture", "generation": 1},
        ),
        (
            [
                health.SubscriptionRecord(
                    symbol="rb2401.SHFE",
                    subscription_id="sub-rb",
                    created_at=datetime.now(CHINA_TZ),
                    last_tick_at=datetime.now(CHINA_TZ),
                    active=True,
                )
            ],
            {"source": "fixture", "generation": 2},
        ),
    ]

    async def fake_active(_args, _logger):
        return snapshots.pop(0)

    remediation_result = health.RemediationResult(
        attempted=True,
        resubscribed=["rb2401.SHFE"],
    )

    async def fake_remediation(
        _args,
        _logger,
        _report,
        *,
        attempt: health.RemediationAttempt,
    ):
        assert attempt.number <= attempt.max_attempts
        return remediation_result

    monkeypatch.setattr(health, "_load_expected_symbols", fake_expected)
    monkeypatch.setattr(health, "_load_active_subscriptions", fake_active)
    monkeypatch.setattr(health, "_perform_remediation", fake_remediation)

    logger = health.configure_logging(None)
    report = await health.run_health_check(args, logger)

    assert report.remediation is remediation_result
    assert report.exit_code == health.EXIT_SUCCESS
    assert report.coverage_ratio == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_enforce_escalates_after_max_attempts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    parser = health.build_parser()
    args = parser.parse_args(
        [
            "--mode",
            "enforce",
            "--skip-metrics",
            "--out-dir",
            str(tmp_path / "out"),
            "--max-remediation-attempts",
            "2",
        ]
    )

    async def fake_expected(_args, _logger):
        return {"rb2401.SHFE"}, {"source": "fixture"}

    async def fake_active(_args, _logger):
        return [], {"source": "fixture"}

    events: list[tuple[str, dict[str, object]]] = []

    def capture_logs(_logger, _level, event: str, **fields: object) -> None:
        events.append((event, fields))

    async def fake_remediation(
        *_args,
        attempt: health.RemediationAttempt,
        **_kwargs,
    ) -> health.RemediationResult:
        events.append(
            (
                "remediation_attempt_invoked",
                {"attempt": attempt.number, "max": attempt.max_attempts},
            )
        )
        return health.RemediationResult(attempted=True)

    monkeypatch.setattr(health, "_load_expected_symbols", fake_expected)
    monkeypatch.setattr(health, "_load_active_subscriptions", fake_active)
    monkeypatch.setattr(health, "_perform_remediation", fake_remediation)
    monkeypatch.setattr(health, "log_json", capture_logs)

    logger = health.configure_logging(None)
    report = await health.run_health_check(args, logger)

    assert report.exit_code == health.EXIT_ERROR
    assert report.metadata.get("escalated") is True
    assert any(evt == "health_check_escalation" for evt, _ in events)
    assert report.remediation is not None
    assert report.remediation.escalated is True
    assert report.remediation.retries == 2


@pytest.mark.asyncio
async def test_perform_remediation_executes_single_rpc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call_counter = {"request": 0, "connect": 0, "close": 0}

    async def fake_request_json(_nc, subject, payload, timeout):
        call_counter["request"] += 1
        assert subject == "md.subscribe.bulk"
        assert payload == {"symbols": ["rb2401.SHFE"]}
        assert timeout == 8.0
        return {"accepted": payload["symbols"], "rejected": []}

    class DummyNC:
        async def close(self) -> None:
            call_counter["close"] += 1

    async def fake_connect(*_args, **_kwargs):
        call_counter["connect"] += 1
        return DummyNC()

    monkeypatch.setattr(health, "_request_json", fake_request_json)
    monkeypatch.setitem(
        sys.modules, "nats", types.SimpleNamespace(connect=fake_connect)
    )

    args = argparse.Namespace(
        nats_url="nats://localhost:4222",
        user=None,
        password=None,
        subscribe_timeout=8.0,
    )
    report = health.HealthReport(
        generated_at=datetime.now(CHINA_TZ),
        coverage_ratio=0.0,
        expected_total=1,
        active_total=0,
        matched_total=0,
        missing_contracts=["rb2401.SHFE"],
        unexpected_contracts=[],
        stalled_contracts=[],
        warnings=[],
        errors=["Missing 1 contracts"],
        exit_code=health.EXIT_ERROR,
        mode="enforce",
    )

    logger = health.configure_logging(None)
    result = await health.perform_remediation(
        args,
        logger,
        report,
        attempt=health.RemediationAttempt(number=1, max_attempts=3),
    )

    assert call_counter["request"] == 1
    assert call_counter["connect"] == 1
    assert call_counter["close"] == 1
    assert result.resubscribed == ["rb2401.SHFE"]
    assert result.failed == []
    assert result.succeeded is True
