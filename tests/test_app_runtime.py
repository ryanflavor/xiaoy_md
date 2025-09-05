"""Application runtime tests for the Market Data Service.

Tests verify that the application can start and stop cleanly,
load configuration properly, and handle signals gracefully.
"""

import asyncio
from multiprocessing import Process
import os
from pathlib import Path
import signal
import sys
import time
from unittest.mock import patch

import pytest


class TestApplicationRuntime:
    """Test suite for application runtime behavior (AC: 5)."""

    def test_application_starts_without_errors(self):
        """Test that the application can be started without exceptions (AC: 5).

        AAA Pattern:
        - Arrange: Set up test environment and import main module
        - Act: Run the main function with a quick timeout
        - Assert: Verify no exceptions were raised
        """

        # Arrange
        def run_app():
            """Run the application in a separate process."""
            # Add src to path for imports
            sys.path.insert(0, str(Path(__file__).parent.parent))

            # Mock the event loop to exit quickly
            with patch("asyncio.Event.wait") as mock_wait:
                mock_wait.return_value = asyncio.Future()
                mock_wait.return_value.set_result(None)

                # Import and run the application
                from src.__main__ import main

                try:
                    main()
                    sys.exit(0)  # Success
                except (SystemExit, KeyboardInterrupt):
                    raise
                except Exception:  # noqa: BLE001
                    sys.exit(1)  # Failure

        # Act
        process = Process(target=run_app)
        process.start()
        process.join(timeout=5)  # Wait up to 5 seconds

        # Assert
        if process.is_alive():
            process.terminate()
            process.join()
            pytest.fail("Application did not start within timeout")

        assert process.exitcode == 0, "Application exited with error"

    def test_application_handles_sigint_gracefully(self):
        """Test that the application handles SIGINT signal gracefully (AC: 4).

        AAA Pattern:
        - Arrange: Start application in separate process
        - Act: Send SIGINT signal
        - Assert: Verify clean shutdown (process terminates)
        """
        # Arrange
        import subprocess

        # Start the application
        process = subprocess.Popen(
            [sys.executable, "-m", "src"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=Path(__file__).parent.parent,
        )

        # Act
        time.sleep(1)  # Let the app start
        process.send_signal(signal.SIGINT)

        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            pytest.fail("Application did not shutdown within timeout on SIGINT")

        # Assert
        # Accept 0 or -2 (SIGINT) as valid exit codes
        assert process.returncode in [
            0,
            -signal.SIGINT,
        ], f"Unexpected exit code: {process.returncode}"

    def test_application_handles_sigterm_gracefully(self):
        """Test that the application handles SIGTERM signal gracefully (AC: 4).

        AAA Pattern:
        - Arrange: Start application in separate process
        - Act: Send SIGTERM signal
        - Assert: Verify clean shutdown (process terminates)
        """
        # Arrange
        import subprocess

        # Start the application
        process = subprocess.Popen(
            [sys.executable, "-m", "src"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=Path(__file__).parent.parent,
        )

        # Act
        time.sleep(1)  # Let the app start
        process.send_signal(signal.SIGTERM)

        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            pytest.fail("Application did not shutdown within timeout on SIGTERM")

        # Assert
        # Accept 0 or -15 (SIGTERM) as valid exit codes
        assert process.returncode in [
            0,
            -signal.SIGTERM,
        ], f"Unexpected exit code: {process.returncode}"


class TestConfiguration:
    """Test suite for configuration loading (AC: 3)."""

    def test_configuration_loads_from_environment(self):
        """Test that configuration loads from environment variables (AC: 3).

        AAA Pattern:
        - Arrange: Set environment variables
        - Act: Import and load configuration
        - Assert: Verify configuration values match environment
        """
        # Arrange
        test_env = {
            "APP_NAME": "test-service",
            "APP_VERSION": "0.0.1",
            "ENVIRONMENT": "testing",
            "LOG_LEVEL": "DEBUG",
            "NATS_URL": "nats://test:4222",
        }

        # Act
        with patch.dict(os.environ, test_env, clear=False):
            # Re-import to get fresh settings
            import importlib

            import src.config

            importlib.reload(src.config)
            from src.config import settings

            # Assert
            assert settings.app_name == "test-service"
            assert settings.app_version == "0.0.1"
            assert settings.environment == "testing"
            assert settings.log_level == "DEBUG"
            assert settings.nats_url == "nats://test:4222"

    def test_configuration_uses_defaults(self):
        """Test that configuration uses defaults when env vars not set (AC: 3).

        AAA Pattern:
        - Arrange: Clear relevant environment variables
        - Act: Load configuration
        - Assert: Verify default values are used
        """
        # Arrange
        env_to_clear = ["APP_NAME", "APP_VERSION", "ENVIRONMENT", "LOG_LEVEL"]
        # Store original values
        original_env = {k: os.environ.get(k) for k in env_to_clear}

        # Act
        try:
            # Remove the environment variables completely
            for k in env_to_clear:
                if k in os.environ:
                    del os.environ[k]

            # Re-import to get fresh settings
            import importlib

            import src.config

            importlib.reload(src.config)
            from src.config import settings

            # Assert
            assert settings.app_name == "market-data-service"
            assert settings.app_version == "0.1.0"
            assert settings.environment == "development"
            assert settings.log_level == "INFO"
        finally:
            # Restore original environment
            for k, v in original_env.items():
                if v is not None:
                    os.environ[k] = v


class TestApplicationStructure:
    """Test suite for verifying application structure (AC: 1, 2)."""

    def test_hexagonal_architecture_structure_exists(self):
        """Test that Hexagonal architecture directories exist (AC: 1).

        AAA Pattern:
        - Arrange: Define expected structure
        - Act: Check for directory existence
        - Assert: Verify all required directories exist
        """
        # Arrange
        project_root = Path(__file__).parent.parent
        expected_dirs = [
            "src",
            "src/domain",
            "src/application",
            "src/infrastructure",
        ]

        # Act & Assert
        for dir_path in expected_dirs:
            full_path = project_root / dir_path
            assert full_path.exists(), f"Directory {dir_path} does not exist"
            assert full_path.is_dir(), f"{dir_path} is not a directory"

    def test_required_files_exist(self):
        """Test that required files exist in the structure (AC: 1, 2).

        AAA Pattern:
        - Arrange: Define expected files
        - Act: Check for file existence
        - Assert: Verify all required files exist
        """
        # Arrange
        project_root = Path(__file__).parent.parent
        expected_files = [
            "src/__main__.py",
            "src/config.py",
            "src/domain/models.py",
            "src/domain/ports.py",
            "src/application/services.py",
        ]

        # Act & Assert
        for file_path in expected_files:
            full_path = project_root / file_path
            assert full_path.exists(), f"File {file_path} does not exist"
            assert full_path.is_file(), f"{file_path} is not a file"

    def test_application_runs_with_python_m_src(self):
        """Test that application can be run with 'python -m src' (AC: 2).

        AAA Pattern:
        - Arrange: Prepare command to run application
        - Act: Execute command in subprocess
        - Assert: Verify command executes without import errors
        """
        # Arrange
        import subprocess

        # Act
        # Start the application
        process = subprocess.Popen(
            [sys.executable, "-m", "src"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=Path(__file__).parent.parent,
        )

        # Give it a moment to start and check for import errors
        time.sleep(1)

        # Terminate the process
        process.terminate()

        try:
            stdout, stderr = process.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()

        # Assert
        # Check that no import errors occurred
        assert (
            "ImportError" not in stderr
        ), f"Import error when running application: {stderr}"
        assert (
            "ModuleNotFoundError" not in stderr
        ), f"Module not found when running: {stderr}"
        assert (
            "Starting Market Data Service" in stderr
            or "Starting Market Data Service" in stdout
        ), "Application did not start properly"


@pytest.mark.asyncio
class TestAsyncComponents:
    """Test suite for async components (AC: 4)."""

    async def test_service_initialization_and_shutdown(self):
        """Test that MarketDataService initializes and shuts down properly (AC: 4).

        AAA Pattern:
        - Arrange: Create service instance
        - Act: Initialize and shutdown service
        - Assert: Verify no exceptions raised
        """
        # Arrange
        from src.application.services import MarketDataService

        service = MarketDataService()

        # Act & Assert
        try:
            await service.initialize()
            await service.shutdown()
        except (SystemExit, KeyboardInterrupt):
            raise
        except Exception as e:  # noqa: BLE001
            pytest.fail(f"Service initialization/shutdown failed: {e}")

    async def test_service_health_check(self):
        """Test that service health check works (AC: 4).

        AAA Pattern:
        - Arrange: Create and initialize service
        - Act: Run health check
        - Assert: Verify health check returns expected format
        """
        # Arrange
        from src.application.services import MarketDataService

        service = MarketDataService()
        await service.initialize()

        # Act
        health = await service.health_check()

        # Assert
        assert isinstance(health, dict), "Health check should return a dictionary"

        # Cleanup
        await service.shutdown()
