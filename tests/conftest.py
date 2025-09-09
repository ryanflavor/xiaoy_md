"""Shared pytest fixtures for all tests."""

import os
from pathlib import Path
import subprocess

import pytest


@pytest.fixture(scope="session")
def docker_test_image():
    """Build Docker image once per test session and reuse it for all Docker tests.

    This significantly speeds up test execution by building the image only once.
    """
    tag = "market-data-test:pytest"

    # Check if Docker is available
    result = subprocess.run(["docker", "version"], capture_output=True, check=False)
    if result.returncode != 0:
        pytest.skip("Docker not available")

    # Build the image
    build_args = [
        "docker",
        "build",
        "-t",
        tag,
        ".",
    ]

    # Respect explicit CI env; avoid injecting local proxies on CI runners
    ci_env = os.environ.get("GITHUB_ACTIONS") == "true"

    http_proxy = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
    https_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")

    # Only pass proxy build args when provided and not running on CI
    if not ci_env and http_proxy:
        build_args.extend(["--build-arg", f"HTTP_PROXY={http_proxy}"])
    if not ci_env and https_proxy:
        build_args.extend(["--build-arg", f"HTTPS_PROXY={https_proxy}"])

    print(f"\nBuilding Docker image '{tag}' for tests...")
    result = subprocess.run(
        build_args,
        capture_output=True,
        cwd=Path(__file__).parent.parent,
        timeout=300,
        check=False,
    )

    if result.returncode != 0:
        pytest.fail(f"Failed to build Docker image: {result.stderr.decode()}")

    print(f"Docker image '{tag}' built successfully")

    return tag


@pytest.fixture
def docker_available():
    """Check if Docker is available for testing."""
    result = subprocess.run(["docker", "version"], capture_output=True, check=False)
    if result.returncode != 0:
        pytest.skip("Docker not available")
    return True
