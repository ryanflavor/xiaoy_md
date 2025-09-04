"""Market Data Service entry point."""

import asyncio
import logging
import sys

from pythonjsonlogger import jsonlogger

from src.config import settings


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

    logger.info(
        "Starting Market Data Service",
        extra={
            "app_name": settings.app_name,
            "version": settings.app_version,
            "environment": settings.environment,
        },
    )

    try:
        # TODO: Initialize adapters
        # TODO: Initialize domain services
        # TODO: Initialize application services
        # TODO: Start message consumers

        logger.info("Market Data Service started successfully")

        # Keep the service running
        while True:
            await asyncio.sleep(1)

    except KeyboardInterrupt:
        logger.info("Shutting down Market Data Service...")
    except Exception as e:
        logger.exception("Fatal error in Market Data Service", exc_info=e)
        raise
    finally:
        # TODO: Cleanup resources
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
