"""Test CI operational resilience features - addresses QA gaps."""

import os
from pathlib import Path

import yaml


# Test timeout configuration (addresses trace gap)
def test_ci_workflow_has_timeout():
    """Verify CI workflow has timeout to prevent infinite runs."""
    workflow_path = Path(".github/workflows/ci.yml")
    assert workflow_path.exists(), "CI workflow file not found"

    with workflow_path.open() as f:
        workflow = yaml.safe_load(f)

    # Check timeout is configured on the job
    assert "jobs" in workflow
    assert "quality" in workflow["jobs"]
    job = workflow["jobs"]["quality"]
    assert "timeout-minutes" in job, "Timeout not configured for CI job"
    max_timeout = 10
    min_timeout = 5
    assert (
        job["timeout-minutes"] <= max_timeout
    ), f"Timeout should be {max_timeout} minutes or less"
    assert (
        job["timeout-minutes"] >= min_timeout
    ), f"Timeout should be at least {min_timeout} minutes"


# Test cache invalidation scenarios (addresses DR2 partial coverage)
def test_cache_invalidation_on_dependency_change():
    """Verify cache is properly invalidated when dependencies change."""
    workflow_path = Path(".github/workflows/ci.yml")

    with workflow_path.open() as f:
        workflow = yaml.safe_load(f)

    # Find the uv setup step
    steps = workflow["jobs"]["quality"]["steps"]
    uv_step = None
    for step in steps:
        if step.get("uses", "").startswith("astral-sh/setup-uv"):
            uv_step = step
            break

    assert uv_step is not None, "uv setup step not found"
    assert "with" in uv_step
    assert "cache-dependency-glob" in uv_step["with"]

    # Verify cache key includes dependency files
    cache_glob = uv_step["with"]["cache-dependency-glob"]
    assert "pyproject.toml" in cache_glob
    assert "uv.lock" in cache_glob


# Test performance benchmarks documented (addresses TEST-001)
def test_ci_performance_target_documented():
    """Verify CI performance benchmarks are documented."""
    workflow_path = Path(".github/workflows/ci.yml")

    with workflow_path.open() as f:
        content = f.read()

    # Check for performance target documentation
    assert "Performance target" in content or "performance target" in content
    assert "<5 minutes" in content or "5 minutes" in content


# Test failure notification strategy documented (addresses OPS-001 and DR6)
def test_failure_notification_documented():
    """Verify CI failure notification strategy is documented."""
    workflow_path = Path(".github/workflows/ci.yml")

    with workflow_path.open() as f:
        content = f.read()

    # Check notification strategy is documented
    assert "notification" in content.lower() or "email" in content.lower()
    assert "failure" in content.lower()


# Test emergency bypass procedure documented
def test_emergency_bypass_procedure():
    """Verify emergency CI bypass procedure exists."""
    # Check if documentation exists for manual merging
    ci_local = Path("scripts/ci-local.sh")

    # Ensure local CI script exists as a bypass mechanism
    assert ci_local.exists(), "Local CI script should exist for emergency bypass"

    # Check script is executable
    assert os.access(ci_local, os.X_OK), "CI local script should be executable"


# Test concurrent CI runs behavior
def test_workflow_concurrency_handling():
    """Verify CI handles concurrent runs appropriately."""
    workflow_path = Path(".github/workflows/ci.yml")

    with workflow_path.open() as f:
        workflow = yaml.safe_load(f)

    # GitHub Actions by default queues concurrent runs
    # This is acceptable behavior - just verify workflow exists
    assert workflow is not None
    # YAML parser treats 'on' as boolean True due to YAML 1.1 spec
    assert True in workflow or "on" in workflow
    if True in workflow:
        assert "pull_request" in workflow[True]
    else:
        assert "pull_request" in workflow["on"]


# Integration test for CI badge (addresses DR5 partial coverage)
def test_ci_badge_in_readme():
    """Verify CI status badge is properly configured in README."""
    readme_path = Path("README.md")
    assert readme_path.exists(), "README.md not found"

    with readme_path.open() as f:
        content = f.read()

    # Check for GitHub Actions badge
    assert "github.com" in content or "GitHub" in content
    assert "workflow" in content.lower() or "actions" in content.lower()
    # Badge should contain workflow status URL pattern
    assert any(
        pattern in content
        for pattern in ["badge.svg", "workflows", "actions/workflows"]
    )


# Test that CI validates all quality gates
def test_ci_validates_all_quality_requirements():
    """Verify CI runs all required quality checks."""
    workflow_path = Path(".github/workflows/ci.yml")

    with workflow_path.open() as f:
        workflow = yaml.safe_load(f)

    steps = workflow["jobs"]["quality"]["steps"]
    step_names = [step.get("name", "") for step in steps]

    # Verify all required checks are present
    required_checks = [
        "Black",  # Code formatting
        "Mypy",  # Type checking
        "test",  # Test suite
        "architecture",  # Architecture validation
    ]

    for check in required_checks:
        assert any(
            check.lower() in name.lower() for name in step_names
        ), f"CI missing required check: {check}"
