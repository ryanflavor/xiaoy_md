"""Subscription health check orchestration for Market Data Service."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Mapping
import csv
from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
import logging
import os
from pathlib import Path
import shlex
import subprocess  # nosec B404 - subprocess used for operator-defined commands
import sys
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from prometheus_client import CollectorRegistry, Gauge, push_to_gateway

from src.config import AppSettings
from src.operations.full_feed_subscription import (
    ContractsPayloadError,
    RpcResponseDecodeError,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

CHINA_TZ = ZoneInfo("Asia/Shanghai")
EXIT_SUCCESS = 0
EXIT_WARNING = 1
EXIT_ERROR = 2
DEFAULT_WARNING_LAG = 120.0
DEFAULT_CRITICAL_LAG = 300.0
DEFAULT_COVERAGE_THRESHOLD = 0.995
DEFAULT_LOG_PREFIX = "subscription_check"
DEFAULT_JOB_NAME = "subscription_health"
DEFAULT_SUMMARY_ROOT = Path("logs/operations")

logger = logging.getLogger(__name__)
DEFAULT_ESCALATION_MARKER = "subscription_health_escalation"


class SubscriptionPayloadError(ValueError):
    """Raised when a subscription payload lacks required fields."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        super().__init__("invalid_subscription_payload")


class TimestampMissingError(ValueError):
    """Raised when a timestamp field is absent."""

    def __init__(self) -> None:
        super().__init__("timestamp_value_missing")


class TimestampFormatError(ValueError):
    """Raised when a timestamp cannot be parsed."""

    def __init__(self, raw: str) -> None:
        self.raw = raw
        super().__init__(f"invalid_timestamp_format value={raw}")


class CatalogueFormatError(ValueError):
    """Raised when the catalogue format flag is unsupported."""

    def __init__(self, fmt: str) -> None:
        self.format = fmt
        super().__init__(f"unsupported_catalogue_format value={fmt}")


class UnexpectedHealthCheckError(RuntimeError):
    """Raised when an unexpected failure occurs during the health check."""


class MissingNATSUrlError(RuntimeError):
    """Raised when a required NATS URL is absent."""

    def __init__(self, context: str) -> None:
        super().__init__(f"nats_url_required context={context}")


def _split_symbol_exchange(raw_symbol: str) -> tuple[str, str | None]:
    cleaned = raw_symbol.strip()
    if "." in cleaned:
        base, exchange = cleaned.split(".", 1)
        return base, exchange
    return cleaned, None


@dataclass(slots=True)
class HealthEvaluationConfig:
    """Configuration for evaluating feed health."""

    coverage_threshold: float
    warning_lag: float
    critical_lag: float
    mode: str


@dataclass(slots=True)
class RemediationAttempt:
    """Context for a remediation attempt."""

    number: int
    max_attempts: int


@dataclass(slots=True)
class SubscriptionRecord:
    """Snapshot of an active subscription returned by control plane."""

    symbol: str
    subscription_id: str
    created_at: datetime
    last_tick_at: datetime | None
    active: bool
    exchange: str | None = None

    @property
    def vt_symbol(self) -> str:
        exchange = self.exchange or "UNKNOWN"
        if "." in self.symbol:
            return self.symbol
        if self.symbol.endswith(f".{exchange}"):
            return self.symbol
        return f"{self.symbol}.{exchange}"

    @classmethod
    def from_payload(cls, payload: Any) -> SubscriptionRecord:
        if isinstance(payload, str):
            raw_symbol = payload.strip()
            if not raw_symbol:
                raise SubscriptionPayloadError({"symbol": payload})
            base_symbol, exchange = _split_symbol_exchange(raw_symbol)
            now = datetime.now(CHINA_TZ)
            return cls(
                symbol=base_symbol,
                subscription_id=raw_symbol,
                created_at=now,
                last_tick_at=now,
                active=True,
                exchange=exchange,
            )

        symbol_raw = payload.get("symbol") or payload.get("base_symbol") or ""
        symbol = str(symbol_raw).strip()
        if not symbol:
            raise SubscriptionPayloadError(payload)
        base_symbol, exchange = _split_symbol_exchange(symbol)

        subscription_id_raw = (
            payload.get("subscription_id")
            or payload.get("id")
            or payload.get("subscription")
            or symbol
        )
        subscription_id = str(subscription_id_raw).strip() or base_symbol

        created_raw = payload.get("created_at")
        created_at = _parse_ts(created_raw) if created_raw else datetime.now(CHINA_TZ)
        last_raw = payload.get("last_tick_at")
        last_tick = _parse_ts(last_raw) if last_raw else None
        active = bool(payload.get("active", True))
        exchange_value = str(exchange).strip() if exchange else None
        return cls(
            symbol=base_symbol,
            subscription_id=subscription_id,
            created_at=created_at,
            last_tick_at=last_tick,
            active=active,
            exchange=exchange_value,
        )


@dataclass(slots=True)
class StalledContract:
    """Detail for a stalled contract evaluation."""

    symbol: str
    subscription_id: str
    last_tick_at: datetime | None
    lag_seconds: float | None
    severity: str  # "warning" | "critical" | "unknown"


@dataclass(slots=True)
class RemediationResult:
    attempted: bool = False
    resubscribed: list[str] = field(default_factory=list)
    failed: list[dict[str, str]] = field(default_factory=list)
    rate_limit_events: int = 0
    retries: int = 0
    escalated: bool = False

    @property
    def succeeded(self) -> bool:
        return self.attempted and not self.failed


@dataclass(slots=True)
class HealthReport:
    """Computed health summary for the subscription feed."""

    generated_at: datetime
    coverage_ratio: float
    expected_total: int
    active_total: int
    matched_total: int
    exit_code: int
    mode: str
    missing_contracts: list[str] = field(default_factory=list)
    unexpected_contracts: list[str] = field(default_factory=list)
    stalled_contracts: list[StalledContract] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    ignored_symbols: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    remediation: RemediationResult | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at.astimezone(CHINA_TZ).isoformat(),
            "mode": self.mode,
            "coverage_ratio": round(self.coverage_ratio, 6),
            "expected_total": self.expected_total,
            "active_total": self.active_total,
            "matched_total": self.matched_total,
            "ignored_total": len(self.ignored_symbols),
            "ignored_symbols": self.ignored_symbols,
            "missing_contracts": self.missing_contracts,
            "unexpected_contracts": self.unexpected_contracts,
            "stalled_contracts": [
                {
                    "symbol": item.symbol,
                    "subscription_id": item.subscription_id,
                    "last_tick_at": (
                        item.last_tick_at.astimezone(CHINA_TZ).isoformat()
                        if item.last_tick_at
                        else None
                    ),
                    "lag_seconds": item.lag_seconds,
                    "severity": item.severity,
                }
                for item in self.stalled_contracts
            ],
            "warnings": self.warnings,
            "errors": self.errors,
            "exit_code": self.exit_code,
            "metadata": self.metadata,
            "remediation": (
                {
                    "attempted": self.remediation.attempted,
                    "succeeded": self.remediation.succeeded,
                    "resubscribed": self.remediation.resubscribed,
                    "failed": self.remediation.failed,
                    "rate_limit_events": self.remediation.rate_limit_events,
                    "retries": self.remediation.retries,
                }
                if self.remediation
                else None
            ),
        }


def _parse_ts(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC).astimezone(CHINA_TZ)
        return value.astimezone(CHINA_TZ)
    if not value:
        raise TimestampMissingError
    raw = str(value)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TimestampFormatError(raw) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(CHINA_TZ)


def configure_logging(log_file: Path | None = None) -> logging.Logger:
    logger = logging.getLogger("operations.check_feed_health")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("%(message)s")
    stdout_handler = logging.StreamHandler()
    stdout_handler.setFormatter(formatter)
    logger.addHandler(stdout_handler)
    if log_file is not None:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    logger.propagate = False
    return logger


def log_json(logger: logging.Logger, level: int, event: str, **fields: Any) -> None:
    payload = {"event": event, **fields}
    logger.log(level, json.dumps(payload, ensure_ascii=False))


async def run_health_check(
    args: argparse.Namespace, logger: logging.Logger
) -> HealthReport:
    settings = AppSettings()
    expected_symbols, expected_meta = await _load_expected_symbols(args, logger)
    active_records, active_meta = await _load_active_subscriptions(args, logger)

    evaluation_config = HealthEvaluationConfig(
        coverage_threshold=args.coverage_threshold,
        warning_lag=args.lag_warning,
        critical_lag=args.lag_critical,
        mode=args.mode,
    )

    ignored_symbols = _load_ignored_symbols(Path(args.subscription_summary_root))

    report = evaluate_health(
        expected_symbols,
        active_records,
        config=evaluation_config,
        ignored_symbols=ignored_symbols,
    )
    report.metadata.update(
        {
            "expected_source": expected_meta,
            "active_source": active_meta,
            "ignored_count": len(ignored_symbols),
            "ignored_source": str(Path(args.subscription_summary_root)),
        }
    )

    remediation: RemediationResult | None = None
    attempts = 0
    remediated = False

    if args.mode == "enforce" and report.exit_code == EXIT_ERROR:
        max_attempts = max(1, int(args.max_remediation_attempts))
        while report.exit_code == EXIT_ERROR and attempts < max_attempts:
            attempts += 1
            remediation = await _perform_remediation(
                args,
                logger,
                report,
                attempt=RemediationAttempt(number=attempts, max_attempts=max_attempts),
            )
            report.remediation = remediation

            active_records, active_meta = await _load_active_subscriptions(args, logger)
            updated_report = evaluate_health(
                expected_symbols,
                active_records,
                config=evaluation_config,
                ignored_symbols=ignored_symbols,
            )
            updated_report.metadata.update(
                {
                    "expected_source": expected_meta,
                    "active_source": active_meta,
                    "remediation_attempts": attempts,
                }
            )
            updated_report.remediation = remediation
            report = updated_report
            remediated = report.exit_code != EXIT_ERROR

        if remediation is not None and remediation.retries == 0:
            remediation.retries = attempts
        if attempts:
            report.metadata.setdefault("remediation_attempts", attempts)
            if remediated:
                report.metadata["remediated"] = True
        if report.exit_code == EXIT_ERROR:
            _escalate(logger, report, attempts, args, remediation)

    if not args.skip_metrics:
        _push_metrics(report, settings, args)

    return report


async def _load_expected_symbols(
    args: argparse.Namespace, logger: logging.Logger
) -> tuple[set[str], dict[str, Any]]:
    if args.catalogue:
        symbols = _load_catalogue_file(args.catalogue, args.catalogue_format)
        log_json(
            logger,
            logging.INFO,
            "catalogue_loaded",
            source="file",
            path=str(args.catalogue),
            total=len(symbols),
        )
        return symbols, {"source": "file", "path": str(args.catalogue)}

    if args.nats_url is None:
        raise MissingNATSUrlError("catalogue")

    import nats  # lazy import

    nc = await nats.connect(
        args.nats_url,
        user=args.user,
        password=args.password,
        name="check-feed-health",
    )
    try:
        payload = await _request_json(
            nc,
            "md.contracts.list",
            {"timeout_s": args.contracts_timeout},
            args.contracts_timeout + 5.0,
        )
        symbols = {
            str(symbol).strip()
            for symbol in payload.get("symbols") or []
            if str(symbol).strip()
        }
        log_json(
            logger,
            logging.INFO,
            "catalogue_loaded",
            source=payload.get("source", "control-plane"),
            total=len(symbols),
        )
        return symbols, {
            "source": payload.get("source", "control-plane"),
            "ts": payload.get("ts"),
        }
    finally:
        await nc.close()


async def _load_active_subscriptions(
    args: argparse.Namespace, logger: logging.Logger
) -> tuple[list[SubscriptionRecord], dict[str, Any]]:
    if args.active_file:
        payload = json.loads(Path(args.active_file).read_text(encoding="utf-8"))
        records = _parse_subscriptions_payload(payload)
        log_json(
            logger,
            logging.INFO,
            "active_snapshot_loaded",
            source="file",
            path=str(args.active_file),
            total=len(records),
        )
        return records, {"source": "file", "path": str(args.active_file)}

    if args.nats_url is None:
        raise MissingNATSUrlError("active_snapshot")

    import nats

    nc = await nats.connect(
        args.nats_url,
        user=args.user,
        password=args.password,
        name="check-feed-health",
    )
    try:
        payload = await _request_json(
            nc,
            "md.subscriptions.active",
            {},
            args.active_timeout,
        )
        records = _parse_subscriptions_payload(payload)
        log_json(
            logger,
            logging.INFO,
            "active_snapshot_loaded",
            source=payload.get("source", "control-plane"),
            total=len(records),
        )
        metadata = {
            "source": payload.get("source", "control-plane"),
            "ts": payload.get("ts"),
        }
        if "error" in payload:
            metadata["error"] = payload["error"]
        return records, metadata
    finally:
        await nc.close()


def _load_catalogue_file(path: Path, fmt: str) -> set[str]:
    if fmt == "auto":
        fmt = "csv" if path.suffix.lower() == ".csv" else "json"

    if fmt == "json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            symbols = payload.get("symbols") or payload.get("items") or []
        else:
            symbols = payload
        return {str(symbol).strip() for symbol in symbols if str(symbol).strip()}

    if fmt == "csv":
        csv_symbols: set[str] = set()
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.reader(handle)
            for row in reader:
                if not row:
                    continue
                symbol = str(row[0]).strip()
                if symbol and not symbol.startswith("#"):
                    csv_symbols.add(symbol)
        return csv_symbols

    raise CatalogueFormatError(fmt)


def _parse_subscriptions_payload(payload: Any) -> list[SubscriptionRecord]:
    if isinstance(payload, dict):
        data = payload.get("subscriptions") or payload.get("items") or []
    else:
        data = payload
    records: list[SubscriptionRecord] = []
    for item in data:
        try:
            if isinstance(item, str | SubscriptionRecord):
                record = SubscriptionRecord.from_payload(item)
            elif isinstance(item, Mapping):
                record = SubscriptionRecord.from_payload(dict(item))
            else:
                record = SubscriptionRecord.from_payload(dict(item))
            records.append(record)
        except (SubscriptionPayloadError, TypeError, ValueError):
            continue
    return records


async def _request_json(
    nc: Any,
    subject: str,
    payload: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    msg = await nc.request(subject, json.dumps(payload).encode(), timeout=timeout)
    data = msg.data.decode()
    try:
        result = json.loads(data)
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        raise RpcResponseDecodeError(subject) from exc
    if not isinstance(result, dict):
        raise ContractsPayloadError.unexpected_response(subject)
    return result


def _classify_stalled_contract(
    record: SubscriptionRecord,
    now: datetime,
    config: HealthEvaluationConfig,
) -> StalledContract | None:
    if not record.active:
        return None

    last_seen = record.last_tick_at
    if last_seen is None:
        return StalledContract(
            symbol=record.vt_symbol,
            subscription_id=record.subscription_id,
            last_tick_at=None,
            lag_seconds=None,
            severity="critical",
        )

    lag_seconds = max(0.0, (now - last_seen).total_seconds())
    if lag_seconds >= config.critical_lag:
        severity = "critical"
    elif lag_seconds >= config.warning_lag:
        severity = "warning"
    else:
        return None

    return StalledContract(
        symbol=record.vt_symbol,
        subscription_id=record.subscription_id,
        last_tick_at=record.last_tick_at,
        lag_seconds=lag_seconds,
        severity=severity,
    )


def evaluate_health(
    expected_symbols: set[str],
    active_records: Sequence[SubscriptionRecord],
    *,
    config: HealthEvaluationConfig,
    ignored_symbols: set[str] | None = None,
) -> HealthReport:
    now = datetime.now(CHINA_TZ)
    ignored_set = {symbol.strip() for symbol in (ignored_symbols or set()) if symbol}
    active_set = {record.vt_symbol for record in active_records if record.active}
    filtered_expected = expected_symbols - ignored_set
    covered = filtered_expected & active_set
    expected_total = len(filtered_expected)
    coverage_ratio = 1.0 if expected_total == 0 else len(covered) / expected_total

    missing = sorted(filtered_expected - active_set)
    unexpected = sorted(active_set - filtered_expected)

    stalled: list[StalledContract] = []
    critical_count = 0
    warning_count = 0
    for record in active_records:
        stalled_entry = _classify_stalled_contract(record, now, config)
        if stalled_entry is None:
            continue
        stalled.append(stalled_entry)
        if stalled_entry.severity == "critical":
            critical_count += 1
        elif stalled_entry.severity == "warning":
            warning_count += 1

    errors: list[str] = []
    warnings: list[str] = []
    if coverage_ratio < config.coverage_threshold:
        errors.append(
            f"Coverage ratio {coverage_ratio:.6f} below threshold {config.coverage_threshold:.3f}"
        )
    if missing:
        errors.append(f"Missing {len(missing)} contracts")
    if critical_count:
        errors.append(f"Detected {critical_count} critical stalled streams")
    if warning_count:
        warnings.append(f"Detected {warning_count} stalled streams (warning)")
    if unexpected:
        warnings.append(f"Unexpected active contracts: {len(unexpected)}")

    exit_code = EXIT_SUCCESS
    if errors:
        exit_code = EXIT_ERROR
    elif warnings:
        exit_code = EXIT_WARNING

    return HealthReport(
        generated_at=now,
        coverage_ratio=coverage_ratio,
        expected_total=expected_total,
        active_total=len(active_set),
        matched_total=len(covered),
        ignored_symbols=sorted(expected_symbols & ignored_set),
        missing_contracts=missing,
        unexpected_contracts=unexpected,
        stalled_contracts=stalled,
        warnings=warnings,
        errors=errors,
        exit_code=exit_code,
        mode=config.mode,
    )


async def _perform_remediation(
    args: argparse.Namespace,
    logger: logging.Logger,
    report: HealthReport,
    *,
    attempt: RemediationAttempt,
) -> RemediationResult:
    remediation = RemediationResult(attempted=True)
    symbols_to_resubscribe = set(report.missing_contracts)
    for entry in report.stalled_contracts:
        if entry.severity == "critical":
            symbols_to_resubscribe.add(entry.symbol)

    if not symbols_to_resubscribe:
        remediation.retries = attempt.number
        log_json(
            logger,
            logging.INFO,
            "remediation_skipped",
            reason="nothing_to_resubscribe",
            attempt=attempt.number,
            max_attempts=attempt.max_attempts,
        )
        return remediation

    import nats

    nc = await nats.connect(
        args.nats_url,
        user=args.user,
        password=args.password,
        name="check-feed-health-remediate",
    )
    try:
        batch = sorted(symbols_to_resubscribe)
        log_json(
            logger,
            logging.INFO,
            "remediation_attempt",
            attempt=attempt.number,
            max_attempts=attempt.max_attempts,
            total=len(batch),
            symbols=batch,
        )
        payload = await _request_json(
            nc,
            "md.subscribe.bulk",
            {"symbols": batch},
            args.subscribe_timeout,
        )
        accepted = [str(item) for item in payload.get("accepted") or []]
        rejected: list[dict[str, str]] = [
            {
                "symbol": str(entry.get("symbol", "")),
                "reason": str(entry.get("reason", "")),
            }
            for entry in (payload.get("rejected") or [])
        ]
        remediation.resubscribed.extend(accepted)
        remediation.failed.extend(rejected)
        remediation.rate_limit_events = sum(
            1 for entry in rejected if "rate limit" in entry.get("reason", "").lower()
        )
        remediation.retries = attempt.number
        log_json(
            logger,
            logging.INFO,
            "remediation_result",
            attempt=attempt.number,
            max_attempts=attempt.max_attempts,
            accepted=len(accepted),
            rejected=len(rejected),
            rate_limit_events=remediation.rate_limit_events,
        )
    finally:
        await nc.close()

    return remediation


async def perform_remediation(
    args: argparse.Namespace,
    logger: logging.Logger,
    report: HealthReport,
    *,
    attempt: RemediationAttempt,
) -> RemediationResult:
    """Execute remediation attempt via public API (for tests/utilities)."""
    return await _perform_remediation(args, logger, report, attempt=attempt)


def _load_ignored_symbols(summary_root: Path) -> set[str]:
    """Load rejected subscription symbols from the most recent summary file."""
    try:
        root = summary_root.parent if summary_root.is_file() else summary_root
        if not root.exists():
            return set()
        summary_files = sorted(
            root.glob("full-feed-*/summary.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for summary_path in summary_files:
            try:
                data = json.loads(summary_path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001  # nosec B112
                continue
            rejected_items = data.get("rejected_items") or data.get("rejected") or []
            ignored = {
                str(item.get("symbol", "")).strip()
                for item in rejected_items
                if isinstance(item, Mapping) and str(item.get("symbol", "")).strip()
            }
            if ignored:
                logger.info(
                    "ignored_rejections_loaded",
                    extra={
                        "summary": str(summary_path),
                        "count": len(ignored),
                    },
                )
                return ignored
    except Exception:  # noqa: BLE001
        logger.warning("ignored_rejections_lookup_failed", exc_info=True)
        return set()
    else:
        return set()


def _escalate(
    logger: logging.Logger,
    report: HealthReport,
    attempts: int,
    args: argparse.Namespace,
    remediation: RemediationResult | None,
) -> None:
    log_json(
        logger,
        logging.ERROR,
        "health_check_escalation",
        marker=args.escalation_marker,
        attempts=attempts,
        exit_code=report.exit_code,
        missing=len(report.missing_contracts),
        stalled=len(report.stalled_contracts),
    )
    report.metadata["escalated"] = True
    report.metadata["escalation_marker"] = args.escalation_marker
    if remediation is not None:
        remediation.escalated = True

    command = getattr(args, "escalation_command", None)
    if not command:
        return

    formatted = command.format(
        marker=args.escalation_marker,
        exit_code=report.exit_code,
    )
    command_parts = shlex.split(formatted)
    try:
        result = subprocess.run(
            command_parts,
            shell=False,
            check=False,
            capture_output=True,
            text=True,
        )  # nosec B603 - command template supplied by trusted operators
        log_json(
            logger,
            logging.INFO,
            "escalation_command_executed",
            marker=args.escalation_marker,
            command=formatted,
            returncode=result.returncode,
            stdout=result.stdout.strip() if result.stdout else "",
            stderr=result.stderr.strip() if result.stderr else "",
        )
    except Exception as exc:  # noqa: BLE001
        log_json(
            logger,
            logging.ERROR,
            "escalation_command_error",
            marker=args.escalation_marker,
            command=formatted,
            error=str(exc),
        )


def _push_metrics(
    report: HealthReport, settings: AppSettings, args: argparse.Namespace
) -> None:
    registry = CollectorRegistry()
    feed = args.feed_label or settings.resolved_metrics_feed()
    account = args.account_label or settings.resolved_metrics_account()
    session_window = args.session_window

    coverage = Gauge(
        "md_subscription_coverage_ratio",
        "Ratio of active subscriptions versus expected contracts",
        ("feed", "account", "session_window"),
        registry=registry,
    )
    missing = Gauge(
        "md_subscription_missing_total",
        "Number of missing subscriptions detected by health check",
        ("feed", "account", "session_window"),
        registry=registry,
    )
    stalled = Gauge(
        "md_subscription_stalled_total",
        "Number of stalled subscriptions detected by health check",
        ("feed", "account", "session_window"),
        registry=registry,
    )

    labels = {"feed": feed, "account": account, "session_window": session_window}
    coverage.labels(**labels).set(report.coverage_ratio)
    missing.labels(**labels).set(len(report.missing_contracts))
    stalled.labels(**labels).set(len(report.stalled_contracts))

    push_to_gateway(
        args.pushgateway_url,
        job=args.metrics_job,
        registry=registry,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Subscription health check for Market Data Service.",
    )
    parser.add_argument(
        "--mode",
        choices=("dry-run", "enforce", "audit"),
        default="dry-run",
        help="dry-run: report only, enforce: remediate, audit: export detailed artifacts",
    )
    parser.add_argument(
        "--catalogue",
        type=Path,
        help="Path to expected contract catalogue (JSON or CSV)",
    )
    parser.add_argument(
        "--catalogue-format",
        choices=("auto", "json", "csv"),
        default="auto",
        help="Catalogue file format (default: auto detect)",
    )
    parser.add_argument(
        "--active-file",
        type=Path,
        help="Path to active subscription snapshot JSON (for offline runs)",
    )
    parser.add_argument(
        "--nats-url",
        default=os.getenv("NATS_URL", "nats://127.0.0.1:4222"),
        help="NATS server URL",
    )
    parser.add_argument("--user", default=os.getenv("NATS_USER"), help="NATS username")
    parser.add_argument(
        "--password", default=os.getenv("NATS_PASSWORD"), help="NATS password"
    )
    parser.add_argument(
        "--contracts-timeout",
        type=float,
        default=5.0,
        help="Timeout for md.contracts.list requests",
    )
    parser.add_argument(
        "--active-timeout",
        type=float,
        default=5.0,
        help="Timeout for md.subscriptions.active requests",
    )
    parser.add_argument(
        "--subscribe-timeout",
        type=float,
        default=8.0,
        help="Timeout for md.subscribe.bulk during remediation",
    )
    parser.add_argument(
        "--coverage-threshold",
        type=float,
        default=DEFAULT_COVERAGE_THRESHOLD,
        help="Required coverage ratio (default 0.995)",
    )
    parser.add_argument(
        "--subscription-summary-root",
        type=Path,
        default=Path(os.getenv("SUBSCRIPTION_SUMMARY_ROOT", str(DEFAULT_SUMMARY_ROOT))),
        help="Directory containing full-feed subscription summaries (default logs/operations)",
    )
    parser.add_argument(
        "--lag-warning",
        type=float,
        default=DEFAULT_WARNING_LAG,
        help="Lag seconds threshold for warning severity",
    )
    parser.add_argument(
        "--lag-critical",
        type=float,
        default=DEFAULT_CRITICAL_LAG,
        help="Lag seconds threshold for critical severity",
    )
    parser.add_argument(
        "--max-remediation-attempts",
        type=int,
        default=3,
        help="Maximum remediation retries in enforce mode before escalation",
    )
    parser.add_argument(
        "--escalation-marker",
        default=DEFAULT_ESCALATION_MARKER,
        help="Structured log marker used when escalation is triggered",
    )
    parser.add_argument(
        "--escalation-command",
        help=(
            "Optional shell command executed on escalation (format placeholders "
            "{marker} and {exit_code} are supported)"
        ),
    )
    parser.add_argument(
        "--out",
        action="append",
        choices=("json", "csv"),
        help="Emit detailed artifacts (can specify multiple times)",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("logs/runbooks"),
        help="Directory for generated artifacts",
    )
    parser.add_argument(
        "--log-prefix",
        default=DEFAULT_LOG_PREFIX,
        help="Prefix for log filename (default subscription_check)",
    )
    parser.add_argument(
        "--skip-metrics",
        action="store_true",
        help="Do not push metrics to Pushgateway",
    )
    parser.add_argument(
        "--pushgateway-url",
        default=os.getenv("PUSHGATEWAY_URL", AppSettings().pushgateway_url),
        help="Pushgateway base URL",
    )
    parser.add_argument(
        "--metrics-job",
        default=DEFAULT_JOB_NAME,
        help="Pushgateway job label",
    )
    parser.add_argument(
        "--feed-label",
        help="Override feed label for metrics (default derived from settings)",
    )
    parser.add_argument(
        "--account-label",
        help="Override account label for metrics",
    )
    parser.add_argument(
        "--session-window",
        default=os.getenv("SESSION_WINDOW", "day"),
        help="Session window label for metrics (default from environment)",
    )
    parser.add_argument(
        "--json-indent",
        type=int,
        default=None,
        help="Indentation for JSON artifacts",
    )
    parser.add_argument(
        "--limit-list",
        type=int,
        default=50,
        help="Maximum entries to print for missing/stalled summaries",
    )
    return parser


def _ensure_outputs(
    report: HealthReport, args: argparse.Namespace, logger: logging.Logger
) -> None:
    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = report.generated_at.astimezone(CHINA_TZ).strftime("%Y%m%d-%H%M%S")
    outputs = set(args.out or [])
    if args.mode == "audit" and not outputs:
        outputs = {"json", "csv"}

    if "json" in outputs:
        path = out_dir / f"subscription_health_{ts}.json"
        path.write_text(
            json.dumps(report.to_dict(), ensure_ascii=False, indent=args.json_indent),
            encoding="utf-8",
        )
        log_json(
            logger,
            logging.INFO,
            "artifact_written",
            format="json",
            path=str(path),
        )
    if "csv" in outputs:
        path = out_dir / f"subscription_health_{ts}.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "symbol",
                    "subscription_id",
                    "last_tick_at",
                    "lag_seconds",
                    "severity",
                ],
            )
            writer.writeheader()
            for item in report.stalled_contracts:
                writer.writerow(
                    {
                        "symbol": item.symbol,
                        "subscription_id": item.subscription_id,
                        "last_tick_at": (
                            item.last_tick_at.astimezone(CHINA_TZ).isoformat()
                            if item.last_tick_at
                            else ""
                        ),
                        "lag_seconds": item.lag_seconds or "",
                        "severity": item.severity,
                    }
                )
        log_json(
            logger,
            logging.INFO,
            "artifact_written",
            format="csv",
            path=str(path),
        )


def summarize_to_stdout(
    report: HealthReport, args: argparse.Namespace, logger: logging.Logger
) -> None:
    limit = max(0, int(args.limit_list))
    summary = report.to_dict()
    if limit and len(summary["missing_contracts"]) > limit:
        summary["missing_contracts_display"] = summary["missing_contracts"][:limit]
        summary["missing_contracts_truncated"] = (
            len(summary["missing_contracts"]) - limit
        )
    if limit and len(summary["stalled_contracts"]) > limit:
        summary["stalled_contracts_display"] = summary["stalled_contracts"][:limit]
        summary["stalled_contracts_truncated"] = (
            len(summary["stalled_contracts"]) - limit
        )
    sys.stdout.write(
        json.dumps(summary, ensure_ascii=False, indent=args.json_indent) + "\n"
    )
    log_json(
        logger,
        logging.INFO,
        "health_report_emitted",
        exit_code=report.exit_code,
        warnings=len(report.warnings),
        errors=len(report.errors),
    )


async def async_main(args: argparse.Namespace) -> HealthReport:
    ts = datetime.now(CHINA_TZ).strftime("%Y%m%d-%H%M%S")
    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    log_file = out_dir / f"{args.log_prefix}_{ts}.log"
    logger = configure_logging(log_file)
    log_json(logger, logging.INFO, "health_check_start", mode=args.mode)
    report = await run_health_check(args, logger)
    _ensure_outputs(report, args, logger)
    summarize_to_stdout(report, args, logger)
    log_json(logger, logging.INFO, "health_check_complete", exit_code=report.exit_code)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        report = asyncio.run(async_main(args))
    except KeyboardInterrupt:  # pragma: no cover - manual cancel
        return EXIT_ERROR
    except (
        CatalogueFormatError,
        ContractsPayloadError,
        RpcResponseDecodeError,
        SubscriptionPayloadError,
        TimestampFormatError,
        TimestampMissingError,
        MissingNATSUrlError,
        UnexpectedHealthCheckError,
        TimeoutError,
        OSError,
        ValueError,
    ) as exc:
        logger = configure_logging()
        log_json(
            logger,
            logging.ERROR,
            "health_check_error",
            error=str(exc),
        )
        return EXIT_ERROR
    return int(report.exit_code)


__all__ = [
    "HealthEvaluationConfig",
    "HealthReport",
    "RemediationAttempt",
    "RemediationResult",
    "StalledContract",
    "SubscriptionRecord",
    "build_parser",
    "evaluate_health",
    "main",
    "perform_remediation",
    "run_health_check",
]
