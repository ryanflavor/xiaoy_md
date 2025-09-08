"""Docker build verification tests for Story 1.4.

These tests validate the Dockerfile structure, build process,
and container runtime requirements.
"""

import os
from pathlib import Path
import re
import subprocess

import pytest

# Treat this module as integration to avoid running during unit-only CI stage
pytestmark = pytest.mark.integration

# Constants
IMAGE_SIZE_LIMIT_MB = 200
MINIMUM_STAGES = 2


def get_docker_build_args(tag: str) -> list:
    """Get Docker build args with proxy from environment or default."""
    args = ["docker", "build", "-t", tag, "."]

    # Default proxy for local environment
    default_proxy = "http://192.168.10.102:10808"

    # Get proxy from environment or use default
    http_proxy = (
        os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy") or default_proxy
    )
    https_proxy = (
        os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or default_proxy
    )

    args.extend(["--build-arg", f"HTTP_PROXY={http_proxy}"])
    args.extend(["--build-arg", f"HTTPS_PROXY={https_proxy}"])

    return args


class TestDockerfileSyntax:
    """Unit tests for Dockerfile syntax and structure validation."""

    def test_dockerfile_exists(self):
        """Test that Dockerfile exists in project root (1.4-UNIT-001)."""
        dockerfile_path = Path(__file__).parent.parent / "Dockerfile"
        assert dockerfile_path.exists(), "Dockerfile not found in project root"

    def test_dockerfile_syntax_valid(self):
        """Validate Dockerfile has correct syntax (1.4-UNIT-001)."""
        dockerfile_path = Path(__file__).parent.parent / "Dockerfile"
        content = dockerfile_path.read_text()

        # Check for required instructions
        assert "FROM" in content, "Dockerfile missing FROM instruction"
        assert "COPY" in content, "Dockerfile missing COPY instruction"
        assert "RUN" in content, "Dockerfile missing RUN instruction"
        assert (
            "ENTRYPOINT" in content or "CMD" in content
        ), "Dockerfile missing ENTRYPOINT or CMD"

    def test_multi_stage_structure(self):
        """Verify multi-stage build structure (1.4-UNIT-002)."""
        dockerfile_path = Path(__file__).parent.parent / "Dockerfile"
        content = dockerfile_path.read_text()

        # Count FROM instructions for multi-stage
        from_count = len(re.findall(r"^FROM\s+", content, re.MULTILINE))
        assert (
            from_count >= MINIMUM_STAGES
        ), f"Expected multi-stage build ({MINIMUM_STAGES}+ FROM), found {from_count}"

        # Check for stage names
        assert (
            "AS builder" in content or "AS build" in content
        ), "Missing build stage name"
        assert (
            "AS runtime" in content or "AS final" in content
        ), "Missing runtime stage name"

    def test_base_image_specification(self):
        """Check base image is properly specified (1.4-UNIT-003)."""
        dockerfile_path = Path(__file__).parent.parent / "Dockerfile"
        content = dockerfile_path.read_text()

        # Verify python:3.13-slim is used
        assert "python:3.13-slim" in content, "Should use python:3.13-slim base image"

        # Check no 'latest' tags are used
        assert ":latest" not in content, "Should not use :latest tags"

    def test_user_directive_exists(self):
        """Validate USER directive for non-root execution (1.4-UNIT-004)."""
        dockerfile_path = Path(__file__).parent.parent / "Dockerfile"
        content = dockerfile_path.read_text()

        # Check for USER directive
        assert re.search(
            r"^USER\s+", content, re.MULTILINE
        ), "Missing USER directive for non-root execution"

        # Verify not using root
        assert "USER root" not in content, "Should not switch to root user"

    def test_healthcheck_instruction(self):
        """Verify HEALTHCHECK instruction exists (1.4-UNIT-005)."""
        dockerfile_path = Path(__file__).parent.parent / "Dockerfile"
        content = dockerfile_path.read_text()

        assert "HEALTHCHECK" in content, "Missing HEALTHCHECK instruction"

    def test_entrypoint_format(self):
        """Check ENTRYPOINT uses correct format (1.4-UNIT-006)."""
        dockerfile_path = Path(__file__).parent.parent / "Dockerfile"
        content = dockerfile_path.read_text()

        # Should use exec form for ENTRYPOINT
        if "ENTRYPOINT" in content:
            assert re.search(
                r'ENTRYPOINT\s+\["python"', content
            ), "ENTRYPOINT should use exec form"
            assert (
                'ENTRYPOINT ["python", "-m", "src"]' in content
            ), "ENTRYPOINT should run 'python -m src'"

    def test_env_variables(self):
        """Validate environment variables are set (1.4-UNIT-007)."""
        dockerfile_path = Path(__file__).parent.parent / "Dockerfile"
        content = dockerfile_path.read_text()

        # Check for Python environment variables
        assert (
            "PYTHONPATH" in content or "PATH" in content
        ), "Should set Python path variables"
        assert (
            "PYTHONDONTWRITEBYTECODE" in content
        ), "Should set PYTHONDONTWRITEBYTECODE"
        assert "PYTHONUNBUFFERED" in content, "Should set PYTHONUNBUFFERED"

    def test_workdir_consistency(self):
        """Check WORKDIR is consistent (1.4-UNIT-008)."""
        dockerfile_path = Path(__file__).parent.parent / "Dockerfile"
        content = dockerfile_path.read_text()

        # Should set WORKDIR
        assert "WORKDIR" in content, "Missing WORKDIR instruction"

        # Check for /app as standard
        assert "WORKDIR /app" in content, "Should use /app as working directory"


class TestDockerignore:
    """Tests for .dockerignore file."""

    def test_dockerignore_exists(self):
        """Test that .dockerignore exists."""
        dockerignore_path = Path(__file__).parent.parent / ".dockerignore"
        assert dockerignore_path.exists(), ".dockerignore not found in project root"

    def test_dockerignore_excludes_dev_artifacts(self):
        """Verify .dockerignore excludes development artifacts."""
        dockerignore_path = Path(__file__).parent.parent / ".dockerignore"
        with open(dockerignore_path) as f:  # noqa: PTH123
            content = f.read()

        # Check for common exclusions
        assert "__pycache__" in content, "Should exclude __pycache__"
        assert ".pytest_cache" in content, "Should exclude .pytest_cache"
        assert ".git" in content, "Should exclude .git"
        assert "tests/" in content or "test" in content, "Should exclude test files"
        assert (
            ".venv" in content or "venv/" in content
        ), "Should exclude virtual environments"

    def test_dockerignore_allows_readme(self):
        """Verify README.md is not ignored (needed for build)."""
        dockerignore_path = Path(__file__).parent.parent / ".dockerignore"
        with open(dockerignore_path) as f:  # noqa: PTH123
            content = f.read()

        # README.md should be explicitly allowed
        assert "!README.md" in content, "Should allow README.md for build"


@pytest.fixture(scope="class")
def built_test_image():
    """Build test image once for all integration tests."""
    tag = "test-market-data:test"
    print(f"\n[DEBUG] Building Docker image '{tag}'...")
    build_args = get_docker_build_args(tag)
    print(f"[DEBUG] Build command: {' '.join(build_args)}")

    result = subprocess.run(
        build_args,
        capture_output=True,
        cwd=Path(__file__).parent.parent,
        timeout=120,
        check=False,
    )

    print(f"[DEBUG] Build completed with returncode: {result.returncode}")
    if result.returncode != 0:
        print(f"[DEBUG] Build stderr: {result.stderr.decode()[:500]}")
        pytest.fail(f"Failed to build test image: {result.stderr.decode()}")

    print(f"[DEBUG] Image '{tag}' built successfully")
    return tag


class TestDockerBuildIntegration:
    """Integration tests for Docker build process."""

    @pytest.mark.skipif(
        subprocess.run(
            ["docker", "version"], capture_output=True, check=False
        ).returncode
        != 0,
        reason="Docker not available",
    )
    def test_docker_build_success(self, built_test_image):
        """Test that Docker image builds successfully (1.4-INT-001)."""
        # Image already built by fixture, just verify it exists
        result = subprocess.run(
            ["docker", "images", built_test_image, "--format", "{{.ID}}"],
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.stdout.strip(), f"Built image {built_test_image} should exist"

    @pytest.mark.skipif(
        subprocess.run(
            ["docker", "version"], capture_output=True, check=False
        ).returncode
        != 0,
        reason="Docker not available",
    )
    def test_image_size_under_limit(self, built_test_image):
        """Check final image size is under 200MB (1.4-INT-007)."""
        # Image already built by fixture, just check size
        result = subprocess.run(
            ["docker", "images", built_test_image, "--format", "{{.Size}}"],
            capture_output=True,
            text=True,
            check=False,
        )

        size_str = result.stdout.strip()
        # Parse size (could be in MB or GB)
        if "GB" in size_str:
            size_mb = float(size_str.replace("GB", "")) * 1024
        else:
            size_mb = float(size_str.replace("MB", ""))

        assert (
            size_mb < IMAGE_SIZE_LIMIT_MB
        ), f"Image size {size_mb}MB exceeds {IMAGE_SIZE_LIMIT_MB}MB limit"

    @pytest.mark.skipif(
        subprocess.run(
            ["docker", "version"], capture_output=True, check=False
        ).returncode
        != 0,
        reason="Docker not available",
    )
    def test_non_root_user_runtime(self, built_test_image):
        """Validate container runs as non-root user (1.4-INT-004)."""
        # Image already built by fixture, just test runtime behavior

        print(f"\n[DEBUG] Running container {built_test_image} to check user ID...")

        # Override entrypoint to run id command
        result = subprocess.run(
            ["docker", "run", "--rm", "--entrypoint", "id", built_test_image, "-u"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,  # Add short timeout
        )

        print(f"[DEBUG] Container run completed with returncode: {result.returncode}")

        uid = result.stdout.strip()
        assert uid != "0", f"Container running as root (uid={uid}), should be non-root"
        assert uid == "1000", f"Expected uid=1000, got uid={uid}"


class TestCIPipelineValidation:
    """Tests for CI pipeline Docker configuration."""

    def test_ci_yaml_syntax(self):
        """Validate CI YAML syntax (1.4-UNIT-010)."""
        ci_path = Path(__file__).parent.parent / ".github" / "workflows" / "ci.yml"
        assert ci_path.exists(), "CI workflow file not found"

        with open(ci_path) as f:  # noqa: PTH123
            content = f.read()

        # Check for docker-build job
        assert "docker-build:" in content, "Missing docker-build job in CI"

    def test_build_dependency_on_quality(self):
        """Check build step depends on quality checks (1.4-UNIT-011)."""
        ci_path = Path(__file__).parent.parent / ".github" / "workflows" / "ci.yml"
        with open(ci_path) as f:  # noqa: PTH123
            content = f.read()

        # Check for needs: quality
        assert (
            "needs: quality" in content
        ), "Docker build should depend on quality checks"

    def test_no_registry_push(self):
        """Verify build does not push to registry (1.4-UNIT-015)."""
        ci_path = Path(__file__).parent.parent / ".github" / "workflows" / "ci.yml"
        with open(ci_path) as f:  # noqa: PTH123
            content = f.read()

        # Check push is false
        assert "push: false" in content, "CI should not push to registry"
