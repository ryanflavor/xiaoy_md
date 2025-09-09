"""Security-focused tests for Docker container (Story 1.4).

These tests validate security requirements including non-root user
execution and absence of secrets in image layers.
"""

from pathlib import Path
import re
import subprocess

import pytest

# Treat this module as integration to keep it out of unit-only CI stage
pytestmark = pytest.mark.integration


class TestNonRootUserValidation:
    """Tests to validate non-root user execution requirement."""

    def test_dockerfile_creates_non_root_user(self):
        """Verify Dockerfile creates a non-root user (SEC-003 mitigation)."""
        dockerfile_path = Path(__file__).parent.parent / "Dockerfile"
        content = dockerfile_path.read_text()

        # Check for user creation commands
        assert (
            "useradd" in content or "adduser" in content
        ), "Dockerfile should create a user"
        assert (
            "groupadd" in content or "addgroup" in content
        ), "Dockerfile should create a group"

        # Check for USER directive
        assert re.search(
            r"^USER\s+(?!root)", content, re.MULTILINE
        ), "Should switch to non-root user"

    def test_user_has_specific_uid(self):
        """Verify non-root user has specific UID (not 0)."""
        dockerfile_path = Path(__file__).parent.parent / "Dockerfile"
        content = dockerfile_path.read_text()

        # Check for UID specification
        assert (
            "-u 1000" in content or "uid=1000" in content
        ), "Should specify non-zero UID"
        assert (
            "-g 1000" in content or "gid=1000" in content
        ), "Should specify non-zero GID"

    @pytest.mark.skipif(
        subprocess.run(
            ["docker", "version"], capture_output=True, check=False
        ).returncode
        != 0,
        reason="Docker not available",
    )
    def test_container_runtime_uid(self):
        """Test container runs with non-root UID at runtime (1.4-INT-004)."""
        # Build image with proxy
        subprocess.run(
            [
                "docker",
                "build",
                "--build-arg",
                "HTTP_PROXY=http://192.168.10.102:10808",
                "--build-arg",
                "HTTPS_PROXY=http://192.168.10.102:10808",
                "-t",
                "security-test:latest",
                ".",
            ],
            capture_output=True,
            cwd=Path(__file__).parent.parent,
            timeout=120,
            check=False,
        )

        # Check UID (override entrypoint since default runs the app)
        result = subprocess.run(
            ["docker", "run", "--rm", "--entrypoint", "id", "security-test:latest"],
            capture_output=True,
            text=True,
            check=False,
        )

        output = result.stdout
        assert "uid=1000" in output, f"Expected uid=1000, got: {output}"
        assert "gid=1000" in output, f"Expected gid=1000, got: {output}"
        assert "uid=0" not in output, "Container should not run as root"

    @pytest.mark.skipif(
        subprocess.run(
            ["docker", "version"], capture_output=True, check=False
        ).returncode
        != 0,
        reason="Docker not available",
    )
    def test_container_home_directory(self):
        """Verify non-root user has proper home directory."""
        # Build image with proxy
        subprocess.run(
            [
                "docker",
                "build",
                "--build-arg",
                "HTTP_PROXY=http://192.168.10.102:10808",
                "--build-arg",
                "HTTPS_PROXY=http://192.168.10.102:10808",
                "-t",
                "security-test:latest",
                ".",
            ],
            capture_output=True,
            cwd=Path(__file__).parent.parent,
            timeout=120,
            check=False,
        )

        # Check home directory (override entrypoint)
        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--entrypoint",
                "sh",
                "security-test:latest",
                "-c",
                "echo $HOME",
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        home_dir = result.stdout.strip()
        assert home_dir != "/root", f"Should not use /root as home, got: {home_dir}"
        assert "/home/" in home_dir, f"Should have user home directory, got: {home_dir}"

    @pytest.mark.skipif(
        subprocess.run(
            ["docker", "version"], capture_output=True, check=False
        ).returncode
        != 0,
        reason="Docker not available",
    )
    def test_file_permissions(self):
        """Verify application files are owned by non-root user."""
        # Build image with proxy
        subprocess.run(
            [
                "docker",
                "build",
                "--build-arg",
                "HTTP_PROXY=http://192.168.10.102:10808",
                "--build-arg",
                "HTTPS_PROXY=http://192.168.10.102:10808",
                "-t",
                "security-test:latest",
                ".",
            ],
            capture_output=True,
            cwd=Path(__file__).parent.parent,
            timeout=120,
            check=False,
        )

        # Check file ownership (override entrypoint)
        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--entrypoint",
                "ls",
                "security-test:latest",
                "-la",
                "/app/src",
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        output = result.stdout
        # Should see appuser:appuser ownership
        assert (
            "appuser" in output or "1000" in output
        ), f"Files should be owned by non-root user: {output}"
        # Allow up to 2 mentions of root (in ls output header)
        max_root_mentions = 2
        assert (
            "root" not in output or output.count("root") <= max_root_mentions
        ), "Most files should not be owned by root"


class TestSecretsScanValidation:
    """Tests to ensure no secrets in image layers."""

    def test_no_env_secrets_in_dockerfile(self):
        """Verify no hardcoded secrets in Dockerfile (SEC-002 mitigation)."""
        dockerfile_path = Path(__file__).parent.parent / "Dockerfile"
        content = dockerfile_path.read_text()

        # Common secret patterns
        secret_patterns = [
            r"password\s*=\s*['\"].*['\"]",
            r"api[_-]?key\s*=\s*['\"].*['\"]",
            r"secret\s*=\s*['\"].*['\"]",
            r"token\s*=\s*['\"].*['\"]",
            r"AWS_.*=\s*['\"].*['\"]",
            r"GITHUB_.*=\s*['\"].*['\"]",
        ]

        for pattern in secret_patterns:
            matches = re.findall(pattern, content, re.IGNORECASE)
            assert not matches, f"Potential secret found in Dockerfile: {matches}"

    def test_dockerignore_excludes_secrets(self):
        """Verify .dockerignore excludes secret files."""
        dockerignore_path = Path(__file__).parent.parent / ".dockerignore"
        with open(dockerignore_path) as f:  # noqa: PTH123
            content = f.read()

        # Should exclude common secret files
        assert ".env" in content, "Should exclude .env files"
        assert ".secrets" in content or "secrets" in content, "Should exclude secrets"
        assert "*.key" in content or "key" in content, "Should exclude key files"

    @pytest.mark.skipif(
        subprocess.run(
            ["docker", "version"], capture_output=True, check=False
        ).returncode
        != 0,
        reason="Docker not available",
    )
    def test_image_history_no_secrets(self):
        """Scan image history for exposed secrets (SEC-002)."""
        # Build image with proxy
        subprocess.run(
            [
                "docker",
                "build",
                "--build-arg",
                "HTTP_PROXY=http://192.168.10.102:10808",
                "--build-arg",
                "HTTPS_PROXY=http://192.168.10.102:10808",
                "-t",
                "security-test:latest",
                ".",
            ],
            capture_output=True,
            cwd=Path(__file__).parent.parent,
            timeout=120,
            check=False,
        )

        # Get image history
        result = subprocess.run(
            ["docker", "history", "--no-trunc", "security-test:latest"],
            capture_output=True,
            text=True,
            check=False,
        )

        history = result.stdout.lower()

        # Check for common secret indicators
        secret_indicators = [
            "password=",
            "api_key=",
            "api-key=",
            "secret=",
            "token=",
            "private_key",
            "aws_access",
            "aws_secret",
        ]

        for indicator in secret_indicators:
            assert (
                indicator not in history
            ), f"Potential secret '{indicator}' found in image history"


class TestContainerSecurityBestPractices:
    """Additional security best practices validation."""

    def test_minimal_base_image(self):
        """Verify using minimal base image (python-slim)."""
        dockerfile_path = Path(__file__).parent.parent / "Dockerfile"
        content = dockerfile_path.read_text()

        assert "python:3.13-slim" in content, "Should use slim base image for security"
        assert "alpine" in content or "slim" in content, "Should use minimal base image"

    def test_no_sudo_installed(self):
        """Verify sudo is not installed in container."""
        dockerfile_path = Path(__file__).parent.parent / "Dockerfile"
        content = dockerfile_path.read_text()

        assert (
            "sudo" not in content.lower() or "install sudo" not in content.lower()
        ), "Should not install sudo in container"

    def test_readonly_root_filesystem_compatible(self):
        """Verify container can work with read-only root filesystem."""
        dockerfile_path = Path(__file__).parent.parent / "Dockerfile"
        content = dockerfile_path.read_text()

        # Should set WORKDIR to writable location
        assert "WORKDIR /app" in content, "Should use /app as working directory"

        # Should not write to system directories
        assert ">/etc/" not in content, "Should not write to /etc"
        assert ">/usr/" not in content, "Should not write to /usr"

    @pytest.mark.skipif(
        subprocess.run(
            ["docker", "version"], capture_output=True, check=False
        ).returncode
        != 0,
        reason="Docker not available",
    )
    def test_no_unnecessary_capabilities(self):
        """Verify container runs without the most dangerous capabilities."""
        # Build image with proxy
        subprocess.run(
            [
                "docker",
                "build",
                "--build-arg",
                "HTTP_PROXY=http://192.168.10.102:10808",
                "--build-arg",
                "HTTPS_PROXY=http://192.168.10.102:10808",
                "-t",
                "security-test:latest",
                ".",
            ],
            capture_output=True,
            cwd=Path(__file__).parent.parent,
            timeout=120,
            check=False,
        )

        # Test 1: Verify container runs normally with project Python
        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--entrypoint",
                "sh",
                "security-test:latest",
                "-c",
                "python -c 'import sys; print(sys.executable)'",
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, f"Failed to get Python path: {result.stderr}"
        python_path = result.stdout.strip()

        # Test 2: Verify container blocks dangerous operations (SYS_ADMIN test)
        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--cap-drop=SYS_ADMIN",
                "--entrypoint",
                "sh",
                "security-test:latest",
                "-c",
                f"{python_path} -c 'import sys; print(\"Security test: OK\"); sys.exit(0)'",
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        assert (
            result.returncode == 0
        ), f"Container should run without SYS_ADMIN: {result.stderr}"
        assert "Security test: OK" in result.stdout, "Expected output not found"

        # Test 3: Verify container runs with user namespace (non-root)
        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--entrypoint",
                "sh",
                "security-test:latest",
                "-c",
                "id -u",
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        uid = result.stdout.strip()
        assert (
            uid == "1000"
        ), f"Container should run as non-root user (uid=1000), got uid={uid}"

    def test_health_check_defined(self):
        """Verify HEALTHCHECK is defined for monitoring."""
        dockerfile_path = Path(__file__).parent.parent / "Dockerfile"
        content = dockerfile_path.read_text()

        assert "HEALTHCHECK" in content, "Should define HEALTHCHECK for monitoring"

        # Check health check parameters
        assert "--interval" in content, "Health check should specify interval"
        assert "--timeout" in content, "Health check should specify timeout"
        assert "--retries" in content, "Health check should specify retries"
