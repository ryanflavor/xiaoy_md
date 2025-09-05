"""Market Data Service entry point."""

import asyncio
import logging
import signal
import sys

from pythonjsonlogger import jsonlogger

from src.application.services import MarketDataService
from src.config import settings
from src.infrastructure.nats_publisher import NATSPublisher


def setup_logging() -> None:
    """Configure application logging."""
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    handler = logging.StreamHandler()
    if settings.log_format == "json":
        formatter: logging.Formatter = jsonlogger.JsonFormatter(  # type: ignore[attr-defined]
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


async def run_service() -> None:
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

    try:
        # Initialize service components
        # Create NATS publisher with security configuration
        nats_publisher = NATSPublisher(settings)

        # Create service with NATS publisher
        service = MarketDataService(publisher_port=nats_publisher)
        await service.initialize()

        logger.info("Market Data Service started successfully")

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
