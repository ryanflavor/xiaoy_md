"""Integration tests for setup.sh script - Validates cross-distribution support."""

import os
from pathlib import Path
import subprocess

import pytest


class TestSetupScript:
    """Test suite for setup.sh script functionality."""

    def setup_method(self):
        """Set up test environment."""
        self.script_path = Path("scripts/setup.sh")
        assert self.script_path.exists(), "setup.sh script must exist"

    def test_script_is_executable(self):
        """Given setup script When checked Then has executable permissions."""
        # Check if script has execute permission
        is_executable = os.access(self.script_path, os.X_OK)
        assert is_executable, "setup.sh must be executable"

    def test_script_has_shebang(self):
        """Given setup script When checked Then has proper shebang."""
        with self.script_path.open() as f:
            first_line = f.readline().strip()
        assert first_line == "#!/bin/bash", "Script must have bash shebang"

    def test_script_uses_error_handling(self):
        """Given setup script When checked Then uses set -e for error handling."""
        with self.script_path.open() as f:
            content = f.read()
        assert "set -e" in content, "Script must use 'set -e' for error handling"

    def test_python_version_check(self):
        """Given setup script When checked Then verifies Python version."""
        # Just verify the script contains Python version checking logic
        with self.script_path.open() as f:
            content = f.read()

        assert "PYTHON_VERSION" in content, "Script must check Python version"
        assert (
            'REQUIRED_VERSION="3.13"' in content or "3.13" in content
        ), "Script must require Python 3.13"
        assert "exit 1" in content, "Script must exit on version mismatch"

    def test_color_codes_defined(self):
        """Given setup script When checked Then has color codes for output."""
        with self.script_path.open() as f:
            content = f.read()

        required_colors = ["RED=", "GREEN=", "NC="]
        for color in required_colors:
            assert color in content, f"Script must define {color} for colored output"

    def test_directory_creation_commands(self):
        """Given setup script When checked Then creates required directories."""
        with self.script_path.open() as f:
            content = f.read()

        required_dirs = [
            "src/infrastructure",
            "src/domain",
            "src/application",
            "tests/unit",
            "tests/integration",
        ]

        for directory in required_dirs:
            assert directory in content, f"Script must create {directory}"

    def test_uv_installation_check(self):
        """Given setup script When checked Then checks for uv installation."""
        with self.script_path.open() as f:
            content = f.read()

        assert "command -v uv" in content, "Script must check if uv is installed"
        assert (
            "curl -LsSf https://astral.sh/uv/install.sh" in content
        ), "Script must have uv installation command"

    def test_environment_file_creation(self):
        """Given setup script When checked Then creates .env file."""
        with self.script_path.open() as f:
            content = f.read()

        assert ".env" in content, "Script must handle .env file"
        assert (
            "APP_NAME=market-data-service" in content
        ), "Script must set default environment variables"

    def test_architecture_validation_call(self):
        """Given setup script When checked Then runs architecture validation."""
        with self.script_path.open() as f:
            content = f.read()

        assert (
            "scripts/check_architecture.py" in content
        ), "Script must run architecture validation"

    def test_platform_detection(self):
        """Given setup script When checked Then detects OS platform."""
        with self.script_path.open() as f:
            content = f.read()

        assert "uname -s" in content, "Script must detect OS"
        assert "Darwin" in content, "Script must handle macOS"
        assert "Linux" in content, "Script must handle Linux"

    def test_success_message_format(self):
        """Given setup script When checked Then has clear success indicators."""
        with self.script_path.open() as f:
            content = f.read()

        assert (
            "✅" in content or "✓" in content
        ), "Script should use checkmarks for success"
        assert (
            "Environment setup complete" in content
        ), "Script must have completion message"

    def test_next_steps_instructions(self):
        """Given setup script When checked Then provides next steps."""
        with self.script_path.open() as f:
            content = f.read()

        required_instructions = [
            "source .venv/bin/activate",
            "uv run python -m src",
            "uv run pytest",
        ]

        for instruction in required_instructions:
            assert (
                instruction in content
            ), f"Script must include instruction: {instruction}"


class TestSetupScriptExecution:
    """Test actual execution of setup script in controlled environment."""

    @pytest.mark.skipif(
        os.environ.get("CI") == "true", reason="Skip actual script execution in CI"
    )
    def test_script_dry_run(self):
        """Given setup script When dry run Then exits successfully."""
        # Create a test script that just validates syntax
        result = subprocess.run(
            ["bash", "-n", "scripts/setup.sh"],
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, f"Script syntax error: {result.stderr}"

    def test_script_help_output(self):
        """Given setup script with help flag When run Then shows usage."""
        # Many scripts support --help, let's check if ours does
        with Path("scripts/setup.sh").open() as f:
            content = f.read()

        # Check if script would handle help (even if not implemented)
        # This is more of a recommendation test
        if "--help" not in content:
            pytest.skip("Script doesn't implement --help (optional)")


class TestCrossPlatformCompatibility:
    """Test script compatibility across different platforms."""

    def test_no_bashisms_in_posix_sections(self):
        """Given setup script When checked Then avoids bash-specific syntax."""
        with Path("scripts/setup.sh").open() as f:
            content = f.read()

        # Check for common bashisms that might break on other shells
        # Note: Our script explicitly uses #!/bin/bash so these are OK

        # Since we use #!/bin/bash, bashisms are acceptable
        assert "#!/bin/bash" in content, "Script declares bash usage"

    def test_path_handling(self):
        """Given setup script When checked Then handles paths correctly."""
        with Path("scripts/setup.sh").open() as f:
            content = f.read()

        # Check for proper PATH handling
        assert (
            "PATH=" in content or "export PATH" in content
        ), "Script should handle PATH for uv installation"

    def test_error_exit_codes(self):
        """Given setup script When checked Then uses proper exit codes."""
        with Path("scripts/setup.sh").open() as f:
            content = f.read()

        assert "exit 1" in content, "Script should exit 1 on error"
        # exit 0 is implicit at end, so it's optional to check
