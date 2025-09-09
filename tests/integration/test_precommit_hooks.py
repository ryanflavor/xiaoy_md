"""Integration tests for pre-commit hook execution.

Tests that pre-commit hooks are properly configured and execute as expected
during git commit operations. These tests verify that code quality tools
(Black, Mypy) are enforced through pre-commit hooks.
"""

from pathlib import Path
import re
import shutil
import subprocess
import tempfile

import pytest

# Mark this module as integration to keep it out of unit-only CI stage
pytestmark = pytest.mark.integration


class TestPreCommitHooks:
    """Test suite for pre-commit hook execution validation."""

    @pytest.fixture
    def temp_repo(self):
        """Create a temporary git repository with pre-commit configured."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)

            # Initialize git repo
            subprocess.run(
                ["git", "init"], cwd=repo_path, check=True, capture_output=True
            )
            subprocess.run(
                ["git", "config", "user.email", "test@example.com"],
                cwd=repo_path,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test User"],
                cwd=repo_path,
                check=True,
                capture_output=True,
            )

            # Copy pre-commit config from main project
            precommit_config = (
                Path(__file__).parent.parent.parent / ".pre-commit-config.yaml"
            )
            if precommit_config.exists():
                shutil.copy(precommit_config, repo_path / ".pre-commit-config.yaml")

            # Copy pyproject.toml for tool configurations
            pyproject = Path(__file__).parent.parent.parent / "pyproject.toml"
            if pyproject.exists():
                shutil.copy(pyproject, repo_path / "pyproject.toml")

            yield repo_path

    def test_precommit_config_exists(self):
        """Test that .pre-commit-config.yaml exists in the project root.

        Given: Project repository structure
        When: Pre-commit configuration is checked
        Then: Configuration file exists with proper content
        """
        config_path = Path(__file__).parent.parent.parent / ".pre-commit-config.yaml"
        assert config_path.exists(), ".pre-commit-config.yaml not found in project root"

        content = config_path.read_text()
        assert (
            "black" in content.lower()
        ), "Black formatter not configured in pre-commit"
        assert (
            "mypy" in content.lower()
        ), "Mypy type checker not configured in pre-commit"

    def test_precommit_hooks_block_unformatted_code(self, temp_repo):
        """Test that pre-commit hooks block commits with unformatted code.

        Given: A Python file with formatting violations
        When: Attempting to commit the file
        Then: Pre-commit hooks should block the commit
        """
        # Skip if pre-commit is not installed
        try:
            subprocess.run(["pre-commit", "--version"], capture_output=True, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            pytest.skip("pre-commit not installed")

        # Install pre-commit hooks
        subprocess.run(
            ["pre-commit", "install"], cwd=temp_repo, capture_output=True, check=True
        )

        # Create a Python file with formatting violations
        bad_code = """import os,sys
def badly_formatted_function(   x,y,    z   ):
    return x+y+z
x=[1,2,3,4,5]
"""
        bad_file = temp_repo / "bad_code.py"
        bad_file.write_text(bad_code)

        # Stage the file
        subprocess.run(
            ["git", "add", "bad_code.py"],
            cwd=temp_repo,
            check=True,
            capture_output=True,
        )

        # Try to commit - should fail due to pre-commit hooks
        result = subprocess.run(
            ["git", "commit", "-m", "Test commit with bad formatting"],
            cwd=temp_repo,
            capture_output=True,
            text=True,
            check=False,
        )

        # Pre-commit should prevent the commit (non-zero exit code)
        assert result.returncode != 0, "Pre-commit should block unformatted code"

    def test_precommit_hooks_allow_formatted_code(self, temp_repo):
        """Test that pre-commit hooks allow properly formatted code.

        Given: A Python file with correct formatting and types
        When: Attempting to commit the file
        Then: Pre-commit hooks should allow the commit
        """
        # Skip if pre-commit is not installed
        try:
            subprocess.run(["pre-commit", "--version"], capture_output=True, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            pytest.skip("pre-commit not installed")

        # Create scripts directory and dummy architecture check script
        scripts_dir = temp_repo / "scripts"
        scripts_dir.mkdir(exist_ok=True)
        check_script = scripts_dir / "check_architecture.py"
        check_script.write_text(
            '#!/usr/bin/env python3\n"""Dummy architecture check."""\nimport sys\nsys.exit(0)\n'
        )
        check_script.chmod(0o755)

        # Install pre-commit hooks
        subprocess.run(
            ["pre-commit", "install"], cwd=temp_repo, capture_output=True, check=True
        )

        # Create a properly formatted Python file (with correct Black formatting)
        good_code = '''"""Module with properly formatted code."""


def well_formatted_function(x: int, y: int, z: int) -> int:
    """Add three numbers together.

    Args:
        x: First number
        y: Second number
        z: Third number

    Returns:
        Sum of the three numbers

    """
    return x + y + z


numbers = [1, 2, 3, 4, 5]
'''
        good_file = temp_repo / "good_code.py"
        good_file.write_text(good_code)

        # Create an __init__.py with docstring
        init_file = temp_repo / "__init__.py"
        init_file.write_text('"""Package initialization."""\n')

        # Create .secrets.baseline file for detect-secrets hook
        secrets_baseline = temp_repo / ".secrets.baseline"
        secrets_baseline.write_text('{"version": "1.4.0", "results": {}}\n')

        # Create README.md (required by pyproject.toml for hatchling)
        readme = temp_repo / "README.md"
        readme.write_text("# Test Project\n")

        # Stage the files
        subprocess.run(
            ["git", "add", "good_code.py", "__init__.py"],
            cwd=temp_repo,
            check=True,
            capture_output=True,
        )

        # Try to commit - should succeed with formatted code
        result = subprocess.run(
            ["git", "commit", "-m", "Test commit with good formatting"],
            cwd=temp_repo,
            capture_output=True,
            text=True,
            check=False,
        )

        # Commit should succeed with properly formatted code
        assert result.returncode == 0, (
            f"Pre-commit should allow properly formatted code. "
            f"stdout={result.stdout}, stderr={result.stderr}"
        )

    def test_precommit_hooks_configuration_matches_tools(self):
        """Test that pre-commit configuration matches pyproject.toml tool configs.

        Given: Pre-commit configuration and pyproject.toml
        When: Configurations are compared
        Then: Tool settings should be consistent
        """
        config_path = Path(__file__).parent.parent.parent / ".pre-commit-config.yaml"
        pyproject_path = Path(__file__).parent.parent.parent / "pyproject.toml"

        assert config_path.exists(), ".pre-commit-config.yaml not found"
        assert pyproject_path.exists(), "pyproject.toml not found"

        config_content = config_path.read_text()
        pyproject_content = pyproject_path.read_text()

        # Check that Black line-length in pre-commit matches pyproject.toml
        if "line-length" in pyproject_content and "[tool.black]" in pyproject_content:
            # Extract line-length from pyproject.toml
            # re module imported at top of file

            match = re.search(r"line-length\s*=\s*(\d+)", pyproject_content)
            if match:
                line_length = match.group(1)
                # Check if same line-length is in pre-commit args
                if "--line-length" in config_content:
                    assert (
                        f"--line-length={line_length}" in config_content
                        or f"--line-length {line_length}" in config_content
                    ), "Black line-length mismatch between configs"

    def test_precommit_installable(self):
        """Test that pre-commit can be installed and configured.

        Given: Project with pre-commit configuration
        When: Pre-commit install is run
        Then: Installation should succeed
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a test git repo
            subprocess.run(["git", "init"], cwd=tmpdir, check=True, capture_output=True)

            # Copy pre-commit config
            config_src = Path(__file__).parent.parent.parent / ".pre-commit-config.yaml"
            if config_src.exists():
                shutil.copy(config_src, Path(tmpdir) / ".pre-commit-config.yaml")

            # Try to install pre-commit (if available)
            try:
                result = subprocess.run(
                    ["pre-commit", "install"],
                    cwd=tmpdir,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                # If pre-commit is available, it should install successfully
                if result.returncode == 0:
                    hook_file = Path(tmpdir) / ".git" / "hooks" / "pre-commit"
                    assert hook_file.exists(), "Pre-commit hook not installed"
            except FileNotFoundError:
                pytest.skip("pre-commit not available in environment")
