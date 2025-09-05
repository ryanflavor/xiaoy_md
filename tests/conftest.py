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

    # Default proxy for local environment
    default_proxy = "http://192.168.10.102:10808"

    # Get proxy from environment or use default
    http_proxy = (
        os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy") or default_proxy
    )
    https_proxy = (
        os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or default_proxy
    )

    build_args.extend(["--build-arg", f"HTTP_PROXY={http_proxy}"])
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
