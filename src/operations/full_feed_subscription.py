"""Utilities to orchestrate live full-feed subscription via control plane."""

from __future__ import annotations

import argparse
import asyncio
from collections import deque
import contextlib
from dataclasses import dataclass, field
import fnmatch
import json
import logging
import os
from pathlib import Path
import time
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    generate_latest,
    start_http_server,
)

from src.config import AppSettings

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterable, Sequence


@dataclass
class BatchResult:
    """Result of a single bulk subscribe batch."""

    index: int
    requested: list[str]
    accepted: list[str]
    rejected: list[dict[str, str]]
    duration_seconds: float
    ts: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "requested": self.requested,
            "accepted": self.accepted,
            "rejected": self.rejected,
            "duration_seconds": round(self.duration_seconds, 3),
            "ts": self.ts,
        }


@dataclass
class WorkflowSummary:
    """Aggregate summary for an orchestration run."""

    contracts_source: str
    contract_file: Path
    output_dir: Path
    total_symbols: int
    session_window: str = "day"
    config_profile: str = "primary"
    processed_symbols: list[str] = field(default_factory=list)
    accepted_symbols: list[str] = field(default_factory=list)
    rejected_items: list[dict[str, str]] = field(default_factory=list)
    skipped_symbols: list[str] = field(default_factory=list)
    batches: list[BatchResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "contracts_source": self.contracts_source,
            "contract_file": str(self.contract_file),
            "output_dir": str(self.output_dir),
            "total_symbols": self.total_symbols,
            "session_window": self.session_window,
            "config_profile": self.config_profile,
            "accepted_count": len(self.accepted_symbols),
            "rejected_count": len(self.rejected_items),
            "skipped_count": len(self.skipped_symbols),
            "processed_symbols": self.processed_symbols,
            "accepted_symbols": self.accepted_symbols,
            "rejected_items": self.rejected_items,
            "skipped_symbols": self.skipped_symbols,
            "batches": [batch.to_dict() for batch in self.batches],
        }


@dataclass(slots=True)
class SubscriptionMetricsLabels:
    """Label values used by the subscription metrics exporter."""

    feed: str
    account: str
    session_window: str


class SubscriptionMetricsExporter:
    """Expose subscription workflow metrics via Prometheus."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        labels: SubscriptionMetricsLabels,
        registry: CollectorRegistry | None = None,
        start_http: bool = True,
    ) -> None:
        """Initialize exporter with networking endpoints and label metadata."""
        self._labels = {
            "feed": labels.feed,
            "account": labels.account,
            "session_window": labels.session_window,
        }
        self._registry = registry or CollectorRegistry()
        self._coverage_gauge = Gauge(
            "md_subscription_coverage_ratio",
            "Ratio of accepted subscriptions versus requested symbols",
            ("feed", "account", "session_window"),
            registry=self._registry,
        )
        self._rate_limit_counter = Counter(
            "md_rate_limit_hits",
            "Total number of rate limit hits encountered by subscription workflow",
            ("feed", "account", "session_window"),
            registry=self._registry,
        )

        if start_http:
            try:
                start_http_server(port, addr=host, registry=self._registry)
                logging.getLogger(__name__).info(
                    "Subscription metrics exporter online",
                    extra={"host": host, "port": port},
                )
            except OSError as exc:
                logging.getLogger(__name__).warning(
                    "subscription_metrics_start_failed",
                    extra={"host": host, "port": port, "error": str(exc)},
                )

    def observe_coverage(self, ratio: float) -> None:
        """Set coverage ratio gauge bounded within [0, 1]."""
        value = max(0.0, min(ratio, 1.0))
        self._coverage_gauge.labels(**self._labels).set(value)

    def increment_rate_limit(self, count: int = 1) -> None:
        """Increment rate limit counter."""
        if count <= 0:
            return
        self._rate_limit_counter.labels(**self._labels).inc(count)

    def scrape(self) -> bytes:
        """Return registry exposition for testing."""
        return generate_latest(self._registry)


class RpcResponseDecodeError(ValueError):
    """Raised when an RPC response payload cannot be decoded."""

    def __init__(self, subject: str) -> None:
        super().__init__(f"invalid JSON response for {subject}")


class ContractsPayloadError(TypeError):
    """Raised when md.contracts.list returns an unexpected payload."""

    def __init__(self, detail: str) -> None:
        super().__init__(f"contracts payload error: {detail}")

    @classmethod
    def unexpected_response(cls, subject: str) -> ContractsPayloadError:
        return cls(f"unexpected response type for {subject}")

    @classmethod
    def missing_symbols(cls) -> ContractsPayloadError:
        return cls("contracts.list response missing symbols list")


class RateLimiter:
    """Asynchronous helper to respect rate limits for bulk operations."""

    def __init__(
        self,
        max_per_window: int,
        window_seconds: float,
        *,
        now_fn: Callable[[], float] | None = None,
        sleep_coro: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        """Initialize rate limiter with optional clock and sleep overrides."""
        self._max = int(max_per_window)
        self._window = float(window_seconds)
        self._timestamps: deque[float] = deque()
        self._now_override = now_fn
        self._sleep_override = sleep_coro

    @property
    def enabled(self) -> bool:
        return self._max > 0 and self._window > 0

    @property
    def current_load(self) -> int:
        return len(self._timestamps)

    async def acquire(self, count: int) -> None:
        if not self.enabled or count <= 0:
            return
        pending = int(max(0, count))
        while True:
            now = self._now()
            self._prune(now)
            if len(self._timestamps) + pending <= self._max:
                for _ in range(pending):
                    self._timestamps.append(now)
                return
            wait = (self._timestamps[0] + self._window) - now
            await self._sleep(max(wait, 0.01))

    def release(self, count: int) -> None:
        if count <= 0:
            return
        to_remove = min(count, len(self._timestamps))
        for _ in range(to_remove):
            self._timestamps.pop()

    def _prune(self, now: float | None = None) -> None:
        if not self.enabled:
            self._timestamps.clear()
            return
        if now is None:
            now = self._now()
        cutoff = now - self._window
        while self._timestamps and self._timestamps[0] <= cutoff:
            self._timestamps.popleft()

    def _now(self) -> float:
        if self._now_override is not None:
            return float(self._now_override())
        return asyncio.get_running_loop().time()

    async def _sleep(self, delay: float) -> None:
        duration = max(delay, 0.0)
        if self._sleep_override is not None:
            await self._sleep_override(duration)
        else:
            await asyncio.sleep(duration)


def _load_env_file(env_file: Path) -> None:
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, value = text.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key in {"NATS_URL", "NATS_USER", "NATS_PASSWORD"}:
            os.environ[key] = value


def _normalize_nats_url(url: str) -> str:
    try:
        parsed = urlparse(url)
        if parsed.hostname == "nats":
            return "nats://127.0.0.1:4222"
    except ValueError:
        return "nats://127.0.0.1:4222"
    return url


def _ensure_output_dir(base: Path) -> Path:
    base.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    out = base / f"full-feed-{ts}"
    out.mkdir(parents=True, exist_ok=False)
    return out


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _filter_symbols(
    symbols: Sequence[str],
    include: list[str] | None,
    exclude: list[str] | None,
    limit: int | None,
    *,
    allow_ampersand: bool,
) -> tuple[list[str], list[str]]:
    canonical: list[str] = []
    seen: set[str] = set()
    skipped_ampersand: list[str] = []
    for symbol in symbols:
        text = str(symbol or "").strip()
        if not text:
            continue
        if not allow_ampersand and "&" in text:
            skipped_ampersand.append(text)
            continue
        if include and not any(fnmatch.fnmatch(text, pattern) for pattern in include):
            continue
        if exclude and any(fnmatch.fnmatch(text, pattern) for pattern in exclude):
            continue
        if text in seen:
            continue
        canonical.append(text)
        seen.add(text)
        if limit is not None and len(canonical) >= limit:
            break
    return canonical, skipped_ampersand


def _chunk(symbols: Sequence[str], size: int) -> Iterable[list[str]]:
    step = max(1, int(size))
    bucket: list[str] = []
    for sym in symbols:
        bucket.append(sym)
        if len(bucket) >= step:
            yield bucket
            bucket = []
    if bucket:
        yield bucket


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
    except json.JSONDecodeError as exc:
        raise RpcResponseDecodeError(subject) from exc
    if not isinstance(result, dict):
        raise ContractsPayloadError.unexpected_response(subject)
    return result


async def _fetch_contracts(
    nc: Any,
    timeout: float,
) -> dict[str, Any]:
    return await _request_json(
        nc, "md.contracts.list", {"timeout_s": timeout}, timeout + 5.0
    )


async def _bulk_subscribe(
    nc: Any,
    symbols: Sequence[str],
    timeout: float,
) -> dict[str, Any]:
    return await _request_json(
        nc, "md.subscribe.bulk", {"symbols": list(symbols)}, timeout
    )


def _configure_logging(verbose: bool) -> logging.Logger:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(message)s")
    return logging.getLogger("full_feed_subscription")


async def run_workflow(  # noqa: PLR0912, PLR0915 - orchestration flow
    args: argparse.Namespace, logger: logging.Logger
) -> WorkflowSummary:
    from nats.aio.client import Client as NATSClient

    settings = AppSettings()
    out_dir = _ensure_output_dir(Path(args.output_dir))
    feed_label = settings.resolved_metrics_feed()
    if feed_label == "auto":
        feed_label = args.config
    account_label = settings.resolved_metrics_account()

    os.environ["ACTIVE_FEED"] = feed_label
    os.environ["ACTIVE_ACCOUNT_MASK"] = account_label

    logger.info("Output directory: %s", out_dir)
    logger.info(
        json.dumps(
            {
                "event": "subscription_context",
                "session_window": args.window,
                "config": args.config,
                "feed": feed_label,
                "account": account_label,
            },
            ensure_ascii=False,
        )
    )

    nc = NATSClient()
    options: dict[str, Any] = {
        "servers": [args.nats_url],
        "name": "full-feed-orchestrator",
    }
    if args.user and args.password:
        options.update({"user": args.user, "password": args.password})
    await nc.connect(**options)

    try:
        contract_response = await _fetch_contracts(nc, args.contracts_timeout)
        symbols = contract_response.get("symbols") or []
        if not isinstance(symbols, list):
            raise ContractsPayloadError.missing_symbols()

        filtered, skipped_ampersand = _filter_symbols(
            symbols,
            args.include or None,
            args.exclude or None,
            args.limit,
            allow_ampersand=args.allow_ampersand,
        )
        logger.info(
            "Retrieved %s symbols (filtered to %s)",
            len(symbols),
            len(filtered),
        )
        if skipped_ampersand:
            logger.info("Skipped %s symbols containing '&'", len(skipped_ampersand))

        contracts_path = out_dir / "contracts.json"
        contracts_path.write_text(
            json.dumps(contract_response, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        summary = WorkflowSummary(
            contracts_source=str(contract_response.get("source", "unknown")),
            contract_file=contracts_path,
            output_dir=out_dir,
            total_symbols=len(filtered),
            session_window=args.window,
            config_profile=args.config,
        )
        summary.processed_symbols = filtered
        summary.skipped_symbols = skipped_ampersand

        metrics_exporter: SubscriptionMetricsExporter | None = None
        if args.metrics_port and args.metrics_port > 0:
            start_http = os.environ.get("PYTEST_CURRENT_TEST") is None
            metrics_exporter = SubscriptionMetricsExporter(
                host=args.metrics_host,
                port=args.metrics_port,
                labels=SubscriptionMetricsLabels(
                    feed=feed_label,
                    account=account_label,
                    session_window=args.window,
                ),
                start_http=start_http,
            )
            metrics_exporter.observe_coverage(0.0)

        if skipped_ampersand:
            skipped_path = out_dir / "skipped_ampersand.json"
            skipped_path.write_text(
                json.dumps(skipped_ampersand, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.info("Skipped ampersand symbols file -> %s", skipped_path)

        summary_path = out_dir / "summary.json"

        if args.dry_run or not filtered:
            logger.info("Dry run selected or no symbols to process; exiting early.")
            summary_path.write_text(
                json.dumps(summary.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.info("Summary written -> %s", summary_path)
            return summary

        limiter = RateLimiter(args.rate_limit_max, args.rate_limit_window)
        pending: deque[str] = deque(filtered)
        accepted_set: set[str] = set()
        retry_counts: dict[str, int] = {}
        batch_index = 0
        rate_limit_hits_total = 0

        while pending:
            batch_symbols: list[str] = []
            while pending and len(batch_symbols) < args.batch_size:
                batch_symbols.append(pending.popleft())
            if not batch_symbols:
                continue

            await limiter.acquire(len(batch_symbols))
            start = time.perf_counter()
            response = await _bulk_subscribe(nc, batch_symbols, args.subscribe_timeout)
            duration = time.perf_counter() - start

            accepted = [str(s) for s in response.get("accepted") or []]
            rejected = [
                {
                    "symbol": str(item.get("symbol", "")),
                    "reason": str(item.get("reason", "")),
                }
                for item in (response.get("rejected") or [])
            ]
            limiter.release(len(batch_symbols) - len(accepted))

            batch_index += 1
            batch = BatchResult(
                index=batch_index,
                requested=batch_symbols,
                accepted=accepted,
                rejected=rejected,
                duration_seconds=duration,
                ts=_timestamp(),
            )
            summary.batches.append(batch)
            (out_dir / f"batch-{batch_index:03d}.json").write_text(
                json.dumps(batch.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            for symbol in accepted:
                if symbol not in accepted_set:
                    summary.accepted_symbols.append(symbol)
                    accepted_set.add(symbol)

            rate_limited: list[str] = []
            actionable_rejections: list[dict[str, str]] = []
            for item in rejected:
                symbol = item.get("symbol", "")
                reason = item.get("reason", "")
                if symbol and "rate limit" in reason.lower():
                    retry_count = retry_counts.get(symbol, 0) + 1
                    if args.max_retries <= 0 or retry_count <= args.max_retries:
                        retry_counts[symbol] = retry_count
                        rate_limited.append(symbol)
                        continue
                    actionable_rejections.append(
                        {
                            "symbol": symbol,
                            "reason": reason,
                            "note": "max_rate_limit_retries_exceeded",
                        }
                    )
                else:
                    actionable_rejections.append(item)

            if actionable_rejections:
                summary.rejected_items.extend(actionable_rejections)
                logger.warning(
                    "Actionable rejections in batch %s: %s",
                    batch_index,
                    actionable_rejections,
                )

            if rate_limited:
                rate_limit_hits_total += len(rate_limited)
                if metrics_exporter is not None:
                    metrics_exporter.increment_rate_limit(len(rate_limited))
                if args.rate_limit_retry_delay > 0:
                    logger.info(
                        "Rate limited for %s symbols; retrying after %.1fs",
                        len(rate_limited),
                        args.rate_limit_retry_delay,
                    )
                    await asyncio.sleep(args.rate_limit_retry_delay)
                for symbol in reversed(rate_limited):
                    pending.appendleft(symbol)

        if summary.rejected_items:
            rejected_path = out_dir / "rejections.json"
            rejected_path.write_text(
                json.dumps(summary.rejected_items, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.info("Recorded actionable rejections -> %s", rejected_path)

        summary_path.write_text(
            json.dumps(summary.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("Summary written -> %s", summary_path)

        if metrics_exporter is not None:
            coverage_ratio = (
                len(summary.accepted_symbols) / summary.total_symbols
                if summary.total_symbols
                else 0.0
            )
            metrics_exporter.observe_coverage(coverage_ratio)
            logger.info(
                "Metrics exported",
                extra={
                    "coverage_ratio": round(coverage_ratio, 4),
                    "rate_limit_hits": rate_limit_hits_total,
                },
            )
        return summary
    finally:
        with contextlib.suppress(Exception):
            await nc.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Automate full-feed subscription via md.contracts.list/md.subscribe.bulk",
    )
    parser.add_argument(
        "--env-file", default=".env", help="Path to env file with NATS/CTP credentials"
    )
    parser.add_argument(
        "--nats-url",
        default=os.getenv("NATS_URL", "nats://127.0.0.1:4222"),
        help="NATS URL (overrides env)",
    )
    parser.add_argument("--user", default=os.getenv("NATS_USER"), help="NATS username")
    parser.add_argument(
        "--password",
        default=os.getenv("NATS_PASSWORD"),
        help="NATS password",
    )
    parser.add_argument(
        "--contracts-timeout",
        type=float,
        default=5.0,
        help="Timeout for md.contracts.list (seconds)",
    )
    parser.add_argument(
        "--subscribe-timeout",
        type=float,
        default=15.0,
        help="Timeout for each md.subscribe.bulk request",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=20000,
        help="Number of symbols per bulk subscribe request",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of symbols (for testing)",
    )
    parser.add_argument(
        "--include", nargs="*", help="Wildcard patterns to include (vt_symbol)"
    )
    parser.add_argument(
        "--exclude",
        nargs="*",
        help="Wildcard patterns to exclude (vt_symbol)",
    )
    parser.add_argument(
        "--output-dir",
        default="logs/operations",
        help="Base directory for run artifacts",
    )
    parser.add_argument(
        "--rate-limit-window",
        type=float,
        default=float(os.getenv("SUBSCRIBE_RATE_LIMIT_WINDOW_SECONDS", "2") or 2.0),
        help="Rate limit window seconds (0 disables client-side throttling)",
    )
    parser.add_argument(
        "--rate-limit-max",
        type=int,
        default=int(os.getenv("SUBSCRIBE_RATE_LIMIT_MAX_REQUESTS", "50000") or 50000),
        help="Max operations per window (0 disables client-side throttling)",
    )
    parser.add_argument(
        "--rate-limit-retry-delay",
        type=float,
        default=0.2,
        help="Delay before retrying symbols rejected with rate limit",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=3,
        help="Max retries for rate-limited symbols (0 = unlimited)",
    )
    parser.add_argument(
        "--allow-ampersand",
        action="store_true",
        help="Include symbols that contain '&' characters",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch contracts only without subscribing",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    parser.add_argument(
        "--window",
        choices=("day", "night"),
        default=os.getenv("SESSION_WINDOW", "day"),
        help="Trading session window (day/night) for logging and artifacts",
    )
    parser.add_argument(
        "--config",
        choices=("primary", "backup"),
        default=os.getenv("SESSION_CONFIG", "primary"),
        help="Configuration profile label (primary/backup) for this run",
    )
    parser.add_argument(
        "--metrics-host",
        default=os.getenv("SUBSCRIPTION_METRICS_HOST", "0.0.0.0"),  # nosec B104
        help="Host interface for Prometheus metrics exporter",
    )
    parser.add_argument(
        "--metrics-port",
        type=int,
        default=int(os.getenv("SUBSCRIPTION_METRICS_PORT", "9101") or 0),
        help="Port for Prometheus metrics exporter (0 disables)",
    )
    parser.add_argument(
        "--metrics-disable",
        action="store_true",
        help="Disable Prometheus metrics exporter",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    _load_env_file(Path(args.env_file))

    if args.metrics_disable:
        args.metrics_port = 0
    elif args.metrics_port < 0:
        parser.error("--metrics-port must be >= 0")

    # Propagate session metadata to environment for downstream tooling.
    os.environ["SESSION_WINDOW"] = args.window
    os.environ["SESSION_CONFIG"] = args.config

    nats_url = _normalize_nats_url(
        args.nats_url or os.getenv("NATS_URL", "nats://127.0.0.1:4222")
    )
    user = args.user if args.user is not None else os.getenv("NATS_USER")
    password = (
        args.password if args.password is not None else os.getenv("NATS_PASSWORD")
    )

    args.nats_url = nats_url
    args.user = user
    args.password = password

    logger = _configure_logging(args.verbose)
    try:
        asyncio.run(run_workflow(args, logger))
    except Exception:
        logger.exception("Workflow failed")
        return 1
    return 0


__all__ = [
    "BatchResult",
    "RateLimiter",
    "SubscriptionMetricsExporter",
    "SubscriptionMetricsLabels",
    "WorkflowSummary",
    "build_parser",
    "main",
    "run_workflow",
]
