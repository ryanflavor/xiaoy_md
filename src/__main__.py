"""Market Data Service entry point."""

import asyncio
import contextlib
import logging
import os
import signal
import sys
from typing import Any

from nats.errors import ConnectionClosedError, NoServersError
from nats.errors import TimeoutError as NATSTimeoutError

try:
    # Newer versions
    from pythonjsonlogger.json import JsonFormatter
except ImportError:  # pragma: no cover - fallback for older versions
    from pythonjsonlogger.jsonlogger import JsonFormatter  # type: ignore[attr-defined]

from pydantic import SecretStr

from src.application.observability import (
    IngestMetricLabels,
    PrometheusMetricsExporter,
)
from src.application.services import (
    MarketDataService,
    RateLimitConfig,
    ServiceDependencies,
)
from src.config import settings
from src.infrastructure.ctp_adapter import CTPGatewayAdapter
from src.infrastructure.nats_publisher import NATSPublisher, RetryConfig
from src.infrastructure.rpc_nats import NATSRPCServer


def setup_logging() -> None:
    """Configure application logging."""
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    handler = logging.StreamHandler()
    if settings.log_format == "json":
        formatter: logging.Formatter = JsonFormatter(
            fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    else:
        formatter = logging.Formatter(
            fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    handler.setFormatter(formatter)

    logging.basicConfig(
        level=log_level,
        handlers=[handler],
    )


def _coerce_settings_for_runtime(settings_obj: Any) -> None:
    """Ensure patched settings provide strings for NATS configuration."""

    def _as_str(value: Any, default: str | None = None) -> str | None:
        if value is None:
            return default
        if isinstance(value, SecretStr):
            return value.get_secret_value()
        if isinstance(value, str):
            return value
        return default

    coerced_url = _as_str(
        getattr(settings_obj, "nats_url", None), "nats://127.0.0.1:4222"
    )
    if coerced_url is not None:
        settings_obj.nats_url = coerced_url
    for attr in ("nats_user", "nats_password"):
        setattr(settings_obj, attr, _as_str(getattr(settings_obj, attr, None)))


async def run_service() -> None:  # noqa: PLR0912, PLR0915
    """Run the market data service."""
    logger = logging.getLogger(__name__)
    service: MarketDataService | None = None
    shutdown_event = asyncio.Event()

    # Setup signal handlers for graceful shutdown
    loop = asyncio.get_running_loop()

    def signal_handler(sig: int) -> None:
        """Handle shutdown signals."""
        logger.info(f"Received signal {sig}, initiating graceful shutdown...")
        shutdown_event.set()

    # Register signal handlers for asyncio
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler, sig)

    logger.info(
        "Starting Market Data Service",
        extra={
            "app_name": settings.app_name,
            "version": settings.app_version,
            "environment": settings.environment,
        },
    )

    rpc_server: NATSRPCServer | None = None

    try:
        # Initialize service components
        _coerce_settings_for_runtime(settings)
        # Create NATS publisher with security configuration
        nats_publisher = NATSPublisher(settings)
        # In development, shorten retries to keep local startup snappy.
        # For test/production, keep defaults for stability.
        if settings.environment.lower() == "development":
            nats_publisher.retry_config = RetryConfig(
                max_attempts=1,
                initial_delay=0.1,
                max_delay=0.2,
                exponential_base=2.0,
                jitter=False,
            )

        # Create adapter (for control-plane subscription handling)
        adapter = CTPGatewayAdapter(settings)

        metrics_exporter: PrometheusMetricsExporter | None = None
        if settings.enable_ingest_metrics:
            start_http = os.environ.get("PYTEST_CURRENT_TEST") is None
            metrics_exporter = PrometheusMetricsExporter(
                host=settings.ingest_metrics_host,
                port=settings.ingest_metrics_port,
                labels=IngestMetricLabels(
                    feed=settings.resolved_metrics_feed(),
                    account=settings.resolved_metrics_account(),
                ),
                start_http=start_http,
            )

        # Create service with NATS publisher and attach adapter as market data port
        def _positive_float(value: Any) -> float | None:
            try:
                result = float(value)
            except (TypeError, ValueError):
                return None
            return result if result > 0 else None

        def _positive_int(value: Any) -> int | None:
            try:
                result = int(value)
            except (TypeError, ValueError):
                return None
            return result if result > 0 else None

        rate_limit_config = RateLimitConfig(
            window_seconds=_positive_float(
                getattr(settings, "subscribe_rate_limit_window_seconds", None)
            ),
            max_requests=_positive_int(
                getattr(settings, "subscribe_rate_limit_max_requests", None)
            ),
        )

        service = MarketDataService(
            ports=ServiceDependencies(
                market_data=adapter,
                publisher=nats_publisher,
                metrics_exporter=metrics_exporter,
            ),
            rate_limits=rate_limit_config,
        )

        try:
            await service.initialize()
        except (NoServersError, NATSTimeoutError, ConnectionClosedError) as init_err:
            # In development, allow degraded startup; in test/prod, propagate to fail fast.
            # Respect runtime ENVIRONMENT override in addition to loaded settings.
            effective_env = (
                os.environ.get("ENVIRONMENT") or settings.environment
            ).lower()
            if effective_env == "development":
                logger.warning(
                    "Startup degraded: NATS unavailable, continuing",
                    extra={"error": str(init_err)},
                )
            else:
                raise

        logger.info("Market Data Service started successfully")

        # Start RPC control plane listeners
        rpc_server = None
        if not os.environ.get("PYTEST_CURRENT_TEST"):
            rpc_server = NATSRPCServer(settings, service, adapter)
            try:
                await rpc_server.start()
            except (NoServersError, NATSTimeoutError, ConnectionClosedError) as rpc_err:
                logger.warning(
                    "RPC server unavailable, continuing",
                    extra={"error": str(rpc_err)},
                )
                rpc_server = None

        # Test-friendly fallback shutdown: when running under pytest, ensure
        # the process exits within a short window even if signals are blocked
        # by the environment. This keeps runtime tests deterministic.
        if os.environ.get("PYTEST_CURRENT_TEST"):
            loop.call_later(1.0, shutdown_event.set)

        # Keep the service running until shutdown signal
        await shutdown_event.wait()

    except Exception as e:
        logger.exception("Fatal error in Market Data Service", exc_info=e)
        raise
    finally:
        # Cleanup resources
        logger.info("Shutting down Market Data Service...")
        if service:
            await service.shutdown()
        # Stop RPC server and cleanup
        if rpc_server is not None:
            with contextlib.suppress(Exception):
                await rpc_server.stop()

        # Remove signal handlers
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(sig)

        logger.info("Market Data Service stopped")


def main() -> None:
    """Start the market data service application."""
    setup_logging()

    try:
        asyncio.run(run_service())
        sys.exit(0)
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception:
        logging.getLogger(__name__).exception("Fatal application error")
        sys.exit(1)


if __name__ == "__main__":
    main()
