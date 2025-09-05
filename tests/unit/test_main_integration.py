"""Unit tests for main application integration with NATS."""

import signal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config import AppSettings

# Test constants
LOG_LEVEL_INFO = 20
EXPECTED_SIGNAL_HANDLER_CALLS = 2


@pytest.fixture
def test_settings():
    """Create test settings."""
    return AppSettings(
        app_name="test-service",
        nats_url="nats://localhost:4222",
        nats_client_id="test-client",
        log_level="INFO",
    )


class TestMainIntegration:
    """Test main application integration."""

    @pytest.mark.asyncio
    async def test_service_initialization_with_nats(self, test_settings):
        """Test service initializes with NATS publisher."""
        with (
            patch("src.__main__.settings", test_settings),
            patch("src.__main__.NATSPublisher") as mock_publisher_class,
            patch("src.__main__.MarketDataService") as mock_service_class,
        ):
            mock_publisher = AsyncMock()
            mock_publisher_class.return_value = mock_publisher

            mock_service = AsyncMock()
            mock_service_class.return_value = mock_service

            # Import after patching
            from src.__main__ import run_service

            # Create shutdown event and trigger it immediately
            with patch("asyncio.Event") as mock_event_class:
                mock_event = AsyncMock()
                mock_event.wait = AsyncMock(return_value=None)
                mock_event_class.return_value = mock_event

                # Mock signal handler setup
                with patch("asyncio.get_running_loop") as mock_get_loop:
                    mock_loop = MagicMock()
                    mock_get_loop.return_value = mock_loop

                    await run_service()

            # Verify NATS publisher was created with settings
            mock_publisher_class.assert_called_once_with(test_settings)

            # Verify service was created with NATS publisher
            mock_service_class.assert_called_once_with(publisher_port=mock_publisher)

            # Verify service was initialized and shutdown
            mock_service.initialize.assert_called_once()
            mock_service.shutdown.assert_called_once()

    @pytest.mark.asyncio
    async def test_graceful_shutdown_on_signal(self, test_settings):
        """Test graceful shutdown on SIGTERM."""
        with (
            patch("src.__main__.settings", test_settings),
            patch("src.__main__.NATSPublisher") as mock_publisher_class,
            patch("src.__main__.MarketDataService") as mock_service_class,
        ):
            mock_publisher = AsyncMock()
            mock_publisher_class.return_value = mock_publisher

            mock_service = AsyncMock()
            mock_service_class.return_value = mock_service

            from src.__main__ import run_service

            # Track if signal handler was called
            signal_handler_called = False

            def track_signal_handler(sig, _handler, *_args):
                nonlocal signal_handler_called
                if sig in (signal.SIGINT, signal.SIGTERM):
                    signal_handler_called = True

            with patch("asyncio.Event") as mock_event_class:
                mock_event = AsyncMock()
                mock_event.wait = AsyncMock(return_value=None)
                mock_event_class.return_value = mock_event

                with patch("asyncio.get_running_loop") as mock_get_loop:
                    mock_loop = MagicMock()
                    mock_loop.add_signal_handler = MagicMock(
                        side_effect=track_signal_handler
                    )
                    mock_get_loop.return_value = mock_loop

                    await run_service()

            # Verify signal handlers were registered
            assert signal_handler_called
            assert (
                mock_loop.add_signal_handler.call_count == EXPECTED_SIGNAL_HANDLER_CALLS
            )

    @pytest.mark.asyncio
    async def test_service_error_handling(self, test_settings):
        """Test service handles initialization errors."""
        with (
            patch("src.__main__.settings", test_settings),
            patch("src.__main__.NATSPublisher") as mock_publisher_class,
            patch("src.__main__.MarketDataService") as mock_service_class,
        ):
            mock_publisher = AsyncMock()
            mock_publisher_class.return_value = mock_publisher

            mock_service = AsyncMock()
            mock_service.initialize.side_effect = RuntimeError("Init failed")
            mock_service_class.return_value = mock_service

            from src.__main__ import run_service

            with patch("asyncio.Event") as mock_event_class:
                mock_event = AsyncMock()
                mock_event_class.return_value = mock_event

                with patch("asyncio.get_running_loop") as mock_get_loop:
                    mock_loop = MagicMock()
                    mock_get_loop.return_value = mock_loop

                    with pytest.raises(RuntimeError, match="Init failed"):
                        await run_service()

            # Verify cleanup was attempted despite error
            mock_service.shutdown.assert_called_once()

    def test_logging_setup(self, test_settings):
        """Test logging configuration."""
        with (
            patch("src.__main__.settings", test_settings),
            patch("logging.basicConfig") as mock_basic_config,
            patch("logging.StreamHandler") as mock_handler_class,
        ):
            mock_handler = MagicMock()
            mock_handler_class.return_value = mock_handler

            from src.__main__ import setup_logging

            setup_logging()

            # Verify logging was configured
            mock_basic_config.assert_called_once()
            config_call = mock_basic_config.call_args
            assert config_call.kwargs["level"] == LOG_LEVEL_INFO

    def test_main_success(self, test_settings):
        """Test main function successful execution."""
        with (
            patch("src.__main__.settings", test_settings),
            patch("src.__main__.setup_logging") as mock_setup_logging,
            patch("asyncio.run") as mock_async_run,
            patch("sys.exit") as mock_exit,
        ):
            from src.__main__ import main

            main()

            mock_setup_logging.assert_called_once()
            mock_async_run.assert_called_once()
            mock_exit.assert_called_once_with(0)

    def test_main_keyboard_interrupt(self, test_settings):
        """Test main function handles KeyboardInterrupt."""
        with (
            patch("src.__main__.settings", test_settings),
            patch("src.__main__.setup_logging"),
            patch("asyncio.run") as mock_async_run,
        ):
            mock_async_run.side_effect = KeyboardInterrupt()
            with patch("sys.exit") as mock_exit:
                from src.__main__ import main

                main()

                mock_exit.assert_called_once_with(0)

    def test_main_exception_handling(self, test_settings):
        """Test main function handles exceptions."""
        with (
            patch("src.__main__.settings", test_settings),
            patch("src.__main__.setup_logging"),
            patch("asyncio.run") as mock_async_run,
            patch("sys.exit") as mock_exit,
            patch("logging.getLogger") as mock_get_logger,
        ):
            mock_async_run.side_effect = RuntimeError("Fatal error")
            mock_logger = MagicMock()
            mock_get_logger.return_value = mock_logger

            from src.__main__ import main

            main()

            mock_logger.exception.assert_called_once_with("Fatal application error")
            mock_exit.assert_called_once_with(1)
