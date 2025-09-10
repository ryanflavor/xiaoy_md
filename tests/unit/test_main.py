"""Unit tests for the main entry point module."""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import src.__main__ as main_module
from src.__main__ import main, run_service, setup_logging


class TestSetupLogging:
    """Test the logging setup functionality."""

    @patch("src.__main__.settings")
    def test_setup_logging_json_format(self, mock_settings):
        """Test JSON logging configuration.

        Given: Settings configured for JSON logging
        When: setup_logging is called
        Then: JSON formatter should be configured
        """
        mock_settings.log_level = "INFO"
        mock_settings.log_format = "json"

        with (
            patch("logging.basicConfig") as mock_basic_config,
            patch("logging.StreamHandler") as mock_handler,
        ):
            setup_logging()

            mock_basic_config.assert_called_once()
            mock_handler.assert_called()

            # Verify log level is set correctly
            call_kwargs = mock_basic_config.call_args[1]
            assert call_kwargs["level"] == logging.INFO

    @patch("src.__main__.settings")
    def test_setup_logging_text_format(self, mock_settings):
        """Test text logging configuration.

        Given: Settings configured for text logging
        When: setup_logging is called
        Then: Text formatter should be configured
        """
        mock_settings.log_level = "DEBUG"
        mock_settings.log_format = "text"

        with (
            patch("logging.basicConfig") as mock_basic_config,
            patch("logging.StreamHandler") as mock_handler,
        ):
            setup_logging()

            mock_basic_config.assert_called_once()
            mock_handler.assert_called()

            # Verify log level is set correctly
            call_kwargs = mock_basic_config.call_args[1]
            assert call_kwargs["level"] == logging.DEBUG

    @patch("src.__main__.settings")
    def test_setup_logging_invalid_level(self, mock_settings):
        """Test logging with invalid level defaults to INFO.

        Given: Invalid log level in settings
        When: setup_logging is called
        Then: Should default to INFO level
        """
        mock_settings.log_level = "INVALID"
        mock_settings.log_format = "text"

        with patch("logging.basicConfig") as mock_basic_config:
            setup_logging()

            call_kwargs = mock_basic_config.call_args[1]
            assert call_kwargs["level"] == logging.INFO


class TestRunService:
    """Test the async service runner."""

    @pytest.mark.asyncio
    @patch("src.__main__.settings")
    @patch("src.__main__.logging.getLogger")
    @patch("src.__main__.MarketDataService")
    async def test_run_service_startup(
        self, mock_service_class, mock_get_logger, mock_settings
    ):
        """Test service startup logging.

        Given: Service is starting
        When: run_service is called
        Then: Should log startup message with app details
        """
        mock_settings.app_name = "test-app"
        mock_settings.app_version = "1.0.0"
        mock_settings.environment = "test"

        mock_logger = MagicMock()
        mock_get_logger.return_value = mock_logger

        # Mock the service
        mock_service = AsyncMock()
        mock_service_class.return_value = mock_service

        # Create a task that sets shutdown_event after startup
        async def trigger_shutdown():
            import asyncio

            await asyncio.sleep(0.01)  # Let startup complete
            # Trigger shutdown by calling signal handler directly

            # Find and call the signal handler
            for call_args in mock_get_logger.return_value.info.call_args_list:
                if "Starting Market Data Service" in str(call_args):
                    # Simulate shutdown by completing the wait
                    return

        # Use asyncio.Event patch to immediately complete
        with patch("asyncio.Event") as mock_event:
            mock_shutdown_event = AsyncMock()
            mock_shutdown_event.wait = AsyncMock(
                return_value=None
            )  # Immediately complete
            mock_event.return_value = mock_shutdown_event

            await run_service()

        # Verify startup logging
        min_startup_log_calls = 2
        assert mock_logger.info.call_count >= min_startup_log_calls
        first_call = mock_logger.info.call_args_list[0]
        assert "Starting Market Data Service" in first_call[0][0]
        assert first_call[1]["extra"]["app_name"] == "test-app"
        assert first_call[1]["extra"]["version"] == "1.0.0"

    @pytest.mark.asyncio
    @patch("src.__main__.logging.getLogger")
    @patch("src.__main__.MarketDataService")
    async def test_run_service_keyboard_interrupt(
        self, mock_service_class, mock_get_logger
    ):
        """Test graceful shutdown on keyboard interrupt.

        Given: Service is running
        When: Shutdown event is triggered
        Then: Should log shutdown message
        """
        mock_logger = MagicMock()
        mock_get_logger.return_value = mock_logger

        # Mock the service
        mock_service = AsyncMock()
        mock_service_class.return_value = mock_service

        # Mock shutdown event to complete immediately
        with patch("asyncio.Event") as mock_event:
            mock_shutdown_event = AsyncMock()
            mock_shutdown_event.wait = AsyncMock(return_value=None)
            mock_event.return_value = mock_shutdown_event

            await run_service()

        # Check for shutdown message
        shutdown_logged = any(
            "Shutting down" in str(call) for call in mock_logger.info.call_args_list
        )
        assert shutdown_logged

    @pytest.mark.asyncio
    @patch("src.__main__.logging.getLogger")
    @patch("src.__main__.MarketDataService")
    async def test_run_service_exception_handling(
        self, mock_service_class, mock_get_logger
    ):
        """Test exception handling in service.

        Given: Service encounters an unexpected error
        When: Exception is raised during execution
        Then: Should log exception and re-raise
        """
        mock_logger = MagicMock()
        mock_get_logger.return_value = mock_logger

        # Make service initialization fail
        test_error = RuntimeError("Test error")
        mock_service_class.side_effect = test_error

        with pytest.raises(RuntimeError) as exc_info:
            await run_service()

        assert str(exc_info.value) == "Test error"
        mock_logger.exception.assert_called_once()

    @pytest.mark.asyncio
    @patch("src.__main__.settings")
    @patch("src.__main__.logging.getLogger")
    @patch("src.__main__.MarketDataService")
    async def test_run_service_continuous_operation(
        self, mock_service_class, mock_get_logger, mock_settings
    ):
        """Test that service continues running until shutdown.

        Given: Service starts successfully
        When: No interruption occurs
        Then: Should continue running until shutdown event
        """
        mock_settings.app_name = "test"
        mock_settings.app_version = "1.0"
        mock_settings.environment = "test"

        mock_logger = MagicMock()
        mock_get_logger.return_value = mock_logger

        # Mock the service
        mock_service = AsyncMock()
        mock_service_class.return_value = mock_service

        # Mock shutdown event to complete after verifying startup
        with patch("asyncio.Event") as mock_event:
            mock_shutdown_event = AsyncMock()
            mock_shutdown_event.wait = AsyncMock(return_value=None)
            mock_event.return_value = mock_shutdown_event

            await run_service()

        # Verify proper startup and shutdown sequence
        mock_service.initialize.assert_called_once()
        mock_service.shutdown.assert_called_once()


class TestMain:
    """Test the main entry point."""

    @patch("src.__main__.setup_logging")
    @patch("src.__main__.asyncio.run")
    @patch("sys.exit")
    def test_main_normal_execution(
        self, mock_exit, mock_asyncio_run, mock_setup_logging
    ):
        """Test normal execution path.

        Given: Application starts normally
        When: main() is called
        Then: Should setup logging and run async service
        """
        # Simulate KeyboardInterrupt to stop the service
        # Prevent coroutine 'never awaited' warnings by closing it inside fake run
        import contextlib

        def _fake_run(coro):
            with contextlib.suppress(Exception):
                coro.close()
            raise KeyboardInterrupt

        mock_asyncio_run.side_effect = _fake_run

        main()

        mock_setup_logging.assert_called_once()
        mock_asyncio_run.assert_called_once()
        mock_exit.assert_called_once_with(0)

    @patch("src.__main__.setup_logging")
    @patch("src.__main__.asyncio.run")
    @patch("sys.exit")
    def test_main_exception_handling(
        self, mock_exit, mock_asyncio_run, mock_setup_logging
    ):
        """Test exception handling in main.

        Given: An unexpected error occurs
        When: main() encounters an exception
        Then: Should exit with error code 1
        """
        import contextlib

        def _fake_run(coro):
            with contextlib.suppress(Exception):
                coro.close()
            raise RuntimeError

        mock_asyncio_run.side_effect = _fake_run

        main()

        mock_setup_logging.assert_called_once()
        mock_asyncio_run.assert_called_once()
        mock_exit.assert_called_once_with(1)

    @patch("src.__main__.setup_logging")
    def test_main_logging_setup_error(self, mock_setup_logging):
        """Test handling of logging setup errors.

        Given: Logging setup fails
        When: main() is called
        Then: Should handle the error gracefully
        """
        mock_setup_logging.side_effect = Exception("Logging setup failed")

        with (
            pytest.raises(Exception, match="Logging setup failed") as exc_info,
            patch("sys.exit"),
        ):
            main()

        assert "Logging setup failed" in str(exc_info.value)


class TestModuleEntry:
    """Test module-level entry point."""

    def test_module_entry_point(self):
        """Test that module can be run as script.

        Given: Module is run directly
        When: __name__ == "__main__"
        Then: main() should be called
        """
        # Import the module with __name__ set to __main__

        # This tests the pattern, though the if __name__ check
        # is already evaluated when the module loads
        assert hasattr(main_module, "main")
        assert callable(main_module.main)
