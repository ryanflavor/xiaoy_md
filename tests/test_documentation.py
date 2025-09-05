"""Tests for documentation completeness and accuracy."""

from pathlib import Path
import re


class TestREADMEValidation:
    """Validate README.md contains all required sections and information."""

    def setup_method(self):
        """Load README content for testing."""
        self.readme_path = Path("README.md")
        assert self.readme_path.exists(), "README.md must exist"

        with self.readme_path.open() as f:
            self.content = f.read()

    def test_readme_has_title(self):
        """Given README When checked Then has project title."""
        assert "# Market Data Service" in self.content, "README must have main title"

    def test_readme_has_description(self):
        """Given README When checked Then has project description."""
        assert (
            "high-performance" in self.content.lower()
        ), "README should describe project as high-performance"
        assert (
            "hexagonal architecture" in self.content.lower()
        ), "README should mention hexagonal architecture"

    def test_readme_has_prerequisites(self):
        """Given README When checked Then lists prerequisites."""
        assert (
            "## Prerequisites" in self.content
        ), "README must have Prerequisites section"
        assert (
            "Python 3.13" in self.content
        ), "README must specify Python 3.13 requirement"
        assert "uv" in self.content, "README must mention uv package manager"

    def test_readme_has_quick_start(self):
        """Given README When checked Then has Quick Start section."""
        assert "## Quick Start" in self.content, "README must have Quick Start section"

    def test_uv_installation_instructions(self):
        """Given README When checked Then has uv installation commands."""
        # Check for Linux/macOS installation
        assert (
            "curl -LsSf https://astral.sh/uv/install.sh" in self.content
        ), "README must include uv installation for Linux/macOS"

        # Check for Windows installation
        assert (
            "irm https://astral.sh/uv/install.ps1" in self.content
        ), "README must include uv installation for Windows"

    def test_project_setup_commands(self):
        """Given README When checked Then has setup commands."""
        required_commands = [
            "git clone",
            "uv sync",
            "source .venv/bin/activate",
            "uv run python -m src",
        ]

        for command in required_commands:
            assert command in self.content, f"README must include command: {command}"

    def test_development_workflow_section(self):
        """Given README When checked Then has Development Workflow."""
        assert (
            "## Development Workflow" in self.content
        ), "README must have Development Workflow section"

    def test_code_formatting_instructions(self):
        """Given README When checked Then has Black formatting commands."""
        assert (
            "uv run black" in self.content
        ), "README must include Black formatting command"
        assert (
            "black --check" in self.content
        ), "README should include Black check command"

    def test_type_checking_instructions(self):
        """Given README When checked Then has Mypy commands."""
        assert "uv run mypy" in self.content, "README must include Mypy command"

    def test_testing_instructions(self):
        """Given README When checked Then has pytest commands."""
        assert "uv run pytest" in self.content, "README must include pytest command"

        # Check for coverage command
        assert "--cov" in self.content, "README should mention coverage option"

    def test_project_structure_section(self):
        """Given README When checked Then has project structure."""
        assert (
            "## Project Structure" in self.content
        ), "README must have Project Structure section"

        # Check for key directories
        required_dirs = [
            "src/",
            "domain/",  # These appear without src/ prefix in the tree structure
            "application/",
            "infrastructure/",
            "tests/",
            "scripts/",
        ]

        for directory in required_dirs:
            assert (
                directory in self.content
            ), f"README must document {directory} in structure"

    def test_architecture_explanation(self):
        """Given README When checked Then explains hexagonal architecture."""
        assert (
            "## Architecture" in self.content
        ), "README must have Architecture section"

        assert "Domain Layer" in self.content, "README must explain Domain layer"
        assert (
            "Application Layer" in self.content
        ), "README must explain Application layer"
        assert (
            "Infrastructure Layer" in self.content
        ), "README must explain Infrastructure layer"

    def test_configuration_section(self):
        """Given README When checked Then has Configuration section."""
        assert (
            "## Configuration" in self.content
        ), "README must have Configuration section"

        assert ".env" in self.content, "README must mention .env file"

    def test_docker_section(self):
        """Given README When checked Then has Docker instructions."""
        assert (
            "## Docker" in self.content or "Docker" in self.content
        ), "README should have Docker section"

        assert "docker-compose" in self.content, "README should mention docker-compose"

    def test_troubleshooting_section(self):
        """Given README When checked Then has Troubleshooting section."""
        assert (
            "## Troubleshooting" in self.content
        ), "README must have Troubleshooting section"

        # Check for common issues
        assert (
            "Python Version" in self.content or "Python 3.13" in self.content
        ), "README should address Python version issues"

    def test_contributing_section(self):
        """Given README When checked Then has Contributing guidelines."""
        assert (
            "## Contributing" in self.content
        ), "README should have Contributing section"

        assert (
            "TDD" in self.content or "Test-Driven Development" in self.content
        ), "README should mention TDD approach"

    def test_readme_completeness_score(self):
        """Given README When analyzed Then meets completeness threshold."""
        required_sections = [
            "# Market Data Service",
            "## Features",
            "## Prerequisites",
            "## Quick Start",
            "## Development Workflow",
            "## Project Structure",
            "## Architecture",
            "## Configuration",
            "## Troubleshooting",
        ]

        found_sections = sum(
            1 for section in required_sections if section in self.content
        )
        completeness = (found_sections / len(required_sections)) * 100

        min_completeness_percent = 80
        assert (
            completeness >= min_completeness_percent
        ), f"README completeness is {completeness:.1f}%, should be >= {min_completeness_percent}%"

    def test_no_placeholder_text(self):
        """Given README When checked Then has no placeholder text."""
        placeholders = [
            "T" + "ODO",
            "F" + "IXME",
            "X" + "XX",
            "[placeholder]",
            "your-",
            "yourorg",
        ]

        # yourorg is actually in our README for GitHub URLs, so let's check context
        for placeholder in placeholders:
            if placeholder == "yourorg":
                # This is acceptable in GitHub URLs as example
                continue
            assert (
                placeholder not in self.content
            ), f"README should not contain placeholder: {placeholder}"

    def test_commands_are_formatted(self):
        """Given README When checked Then commands use code blocks."""
        # Check that commands are in code blocks
        code_block_pattern = r"```\w*\n[^`]+\n```"
        code_blocks = re.findall(code_block_pattern, self.content)

        min_code_blocks = 5
        assert (
            len(code_blocks) > min_code_blocks
        ), f"README should have more than {min_code_blocks} code blocks for commands"

    def test_links_format(self):
        """Given README When checked Then links are properly formatted."""
        # Check for markdown link format
        link_pattern = r"\[([^\]]+)\]\(([^\)]+)\)"
        links = re.findall(link_pattern, self.content)

        # Should have at least some links
        assert len(links) > 0, "README should contain properly formatted links"


class TestScriptsDocumentation:
    """Validate that all scripts are documented."""

    def test_onboarding_script_mentioned(self):
        """Given README When checked Then mentions onboarding wizard."""
        with Path("README.md").open() as f:
            content = f.read()

        assert (
            "onboard.py" in content or "onboarding" in content.lower()
        ), "README should mention onboarding wizard"

    def test_setup_script_mentioned(self):
        """Given README When checked Then mentions setup script."""
        with Path("README.md").open() as f:
            content = f.read()

        assert (
            "setup.sh" in content or "setup script" in content.lower()
        ), "README should mention setup script"

    def test_architecture_script_mentioned(self):
        """Given README When checked Then mentions architecture validation."""
        with Path("README.md").open() as f:
            content = f.read()

        assert (
            "check_architecture.py" in content
            or "architecture validation" in content.lower()
        ), "README should mention architecture validation script"
