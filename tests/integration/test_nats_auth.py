"""Integration tests for NATS authentication."""

import asyncio
from pathlib import Path
import socket
import subprocess
import time

import nats
from nats.errors import NoServersError
import pytest

# Apply reasonable default timeout for all tests in this module
pytestmark = [pytest.mark.integration, pytest.mark.timeout(60)]


def _choose_port(preferred: int) -> int:
    """Choose a free host port, prefer a given one if available."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", preferred))
        except OSError:
            s.bind(("127.0.0.1", 0))
            return int(s.getsockname()[1])
        else:
            return preferred


@pytest.fixture(scope="module")
def nats_auth_container():
    """Start NATS container with authentication enabled.

    Returns mapping with container info and host-mapped ports.
    """
    container_name = "test-nats-auth"

    # Stop and remove any existing container
    subprocess.run(
        ["docker", "rm", "-f", container_name],
        capture_output=True,
        check=False,
    )

    # Resolve config path via pathlib
    current_dir = Path(__file__).resolve().parent
    project_root = current_dir.parent.parent  # Go up 2 levels from tests/integration/
    config_path = project_root / "config" / "nats-server.conf"

    if not config_path.exists():
        raise FileNotFoundError(  # noqa: TRY003 - acceptable for test diagnostic
            f"NATS config not found at {config_path}"
        )

    # Pick host ports (avoid collisions if 4225/8225 are in use)
    client_port = _choose_port(4225)
    monitor_port = _choose_port(8225)

    # Start NATS container with auth config mounted and used via -c
    result = subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            container_name,
            "-p",
            f"{client_port}:4222",
            "-p",
            f"{monitor_port}:8222",
            "-v",
            f"{config_path}:/etc/nats/nats-server.conf:ro",
            "nats:latest",
            "-c",
            "/etc/nats/nats-server.conf",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(  # noqa: TRY003
            f"Failed to start NATS auth container: {result.stderr.strip()}"
        )

    # Wait for NATS to be ready with faster startup check
    time.sleep(2)

    # Verify NATS is actually ready by checking logs (quick check)
    logs_text = ""
    auth_enabled = False
    for _ in range(10):  # Wait up to ~5 seconds
        result = subprocess.run(
            ["docker", "logs", container_name],
            capture_output=True,
            text=True,
            check=False,
        )
        logs_text = result.stdout
        if (
            "Server is ready" in logs_text
            or "Listening for client connections" in logs_text
        ):
            # Heuristic: config parsed line contains 'authorization' when auth block present
            auth_enabled = "authorization" in logs_text.lower()
            break
        time.sleep(0.5)

    yield {
        "name": container_name,
        "client_port": client_port,
        "monitor_port": monitor_port,
        "auth_enabled": auth_enabled,
        "logs": logs_text,
    }

    # Cleanup
    subprocess.run(["docker", "rm", "-f", container_name], check=False)


@pytest.mark.asyncio
async def test_connection_with_valid_credentials(nats_auth_container):
    """Test that connection succeeds with valid credentials."""
    nc = await nats.connect(
        f"nats://localhost:{nats_auth_container['client_port']}",
        user="testuser",  # pragma: allowlist secret
        password="testpass",  # pragma: allowlist secret
        max_reconnect_attempts=1,
        reconnect_time_wait=0.1,
        connect_timeout=3,
    )

    assert nc.is_connected

    # Test publish/subscribe to verify permissions
    sub = await nc.subscribe("test.subject")
    await nc.publish("test.subject", b"test message")

    msg = await sub.next_msg(timeout=1)
    assert msg.data == b"test message"

    await nc.close()


@pytest.mark.asyncio
async def test_connection_without_credentials_fails(nats_auth_container):
    """Test that connection fails without credentials."""

    async def error_cb(e):
        pass  # Suppress error logs

    with pytest.raises(NoServersError):
        await nats.connect(
            f"nats://localhost:{nats_auth_container['client_port']}",
            error_cb=error_cb,
            max_reconnect_attempts=1,
            reconnect_time_wait=0.1,
            connect_timeout=3,
        )


@pytest.mark.asyncio
async def test_connection_with_invalid_credentials_fails(nats_auth_container):
    """Test that connection fails with invalid credentials."""

    async def error_cb(e):
        pass  # Suppress error logs

    with pytest.raises(NoServersError):
        await nats.connect(
            f"nats://localhost:{nats_auth_container['client_port']}",
            user="wronguser",  # pragma: allowlist secret
            password="wrongpass",  # pragma: allowlist secret
            error_cb=error_cb,
            max_reconnect_attempts=1,
            reconnect_time_wait=0.1,
            connect_timeout=3,
        )


@pytest.mark.asyncio
async def test_connection_with_wrong_password_fails(nats_auth_container):
    """Test that connection fails with correct user but wrong password."""

    async def error_cb(e):
        pass  # Suppress error logs

    with pytest.raises(NoServersError):
        await nats.connect(
            f"nats://localhost:{nats_auth_container['client_port']}",
            user="testuser",  # pragma: allowlist secret
            password="wrongpass",  # pragma: allowlist secret
            error_cb=error_cb,
            max_reconnect_attempts=1,
            reconnect_time_wait=0.1,
            connect_timeout=3,
        )


@pytest.mark.asyncio
async def test_multiple_users_can_connect(nats_auth_container):
    """Test that multiple configured users can connect."""
    # Connect as testuser
    nc1 = await nats.connect(
        f"nats://localhost:{nats_auth_container['client_port']}",
        user="testuser",  # pragma: allowlist secret
        password="testpass",  # pragma: allowlist secret
        max_reconnect_attempts=1,
        reconnect_time_wait=0.1,
        connect_timeout=3,
    )
    assert nc1.is_connected

    # Connect as admin
    nc2 = await nats.connect(
        f"nats://localhost:{nats_auth_container['client_port']}",
        user="admin",  # pragma: allowlist secret
        password="testpass",  # pragma: allowlist secret
        max_reconnect_attempts=1,
        reconnect_time_wait=0.1,
        connect_timeout=3,
    )
    assert nc2.is_connected

    # Both should be able to communicate
    # Create subscription and wait for it to be active
    sub = await nc1.subscribe("cross.talk")
    await nc1.flush()  # Ensure subscription is registered

    # Small delay to ensure subscription is fully established
    await asyncio.sleep(0.1)

    # Publish message
    await nc2.publish("cross.talk", b"admin message")
    await nc2.flush()

    # Wait for message with reasonable timeout
    msg = await sub.next_msg(timeout=2)
    assert msg.data == b"admin message"

    await nc1.close()
    await nc2.close()


@pytest.mark.asyncio
async def test_nats_publisher_with_authentication(nats_auth_container):
    """Test NATSPublisher with authentication configured."""
    import os

    from src.config import AppSettings
    from src.infrastructure.nats_publisher import NATSPublisher

    # Set auth environment variables for application (compose uses config by default)
    os.environ["NATS_URL"] = f"nats://localhost:{nats_auth_container['client_port']}"
    os.environ["NATS_USER"] = "testuser"  # pragma: allowlist secret
    os.environ["NATS_PASSWORD"] = "testpass"  # pragma: allowlist secret

    settings = AppSettings()
    publisher = NATSPublisher(settings)

    # Connect should succeed with auth
    await publisher.connect()
    assert await publisher.health_check()

    # Should be able to publish
    await publisher.publish("test.auth", {"message": "authenticated"})

    await publisher.disconnect()

    # Clean up env vars
    del os.environ["NATS_USER"]
    del os.environ["NATS_PASSWORD"]


@pytest.mark.asyncio
async def test_nats_publisher_without_auth_fails(nats_auth_container):
    """Test NATSPublisher fails to connect without auth to secured server."""
    import os

    from src.config import AppSettings
    from src.infrastructure.nats_publisher import NATSPublisher, RetryConfig

    # Clear any existing auth environment variables
    auth_vars_to_clear = ["NATS_USER", "NATS_PASSWORD"]
    original_values = {}
    for var in auth_vars_to_clear:
        if var in os.environ:
            original_values[var] = os.environ[var]
            del os.environ[var]

    # Set URL without auth credentials
    os.environ["NATS_URL"] = f"nats://localhost:{nats_auth_container['client_port']}"

    try:
        # If the container did not enable authorization, skip (environmental issue)
        if not nats_auth_container.get("auth_enabled", False):
            pytest.skip(
                "NATS container did not report authorization enabled; skipping auth failure test"
            )

        settings = AppSettings()
        expected_url = f"nats://localhost:{nats_auth_container['client_port']}"
        assert settings.nats_url == expected_url

        # Create publisher with fast-fail retry config for testing
        publisher = NATSPublisher(settings)
        # Sanity: ensure publisher will target our expected URL
        assert publisher.create_connection_options()["servers"] == [expected_url]
        # Override retry config for faster test execution
        publisher.retry_config = RetryConfig(
            max_attempts=2,  # Only 2 attempts
            initial_delay=0.1,  # 100ms initial delay
            max_delay=1.0,  # Max 1 second
            exponential_base=2.0,
            jitter=False,  # No jitter for predictable timing
        )

        # Connection should fail quickly without auth
        connection_failed = False
        try:
            await publisher.connect()
            # If we get here, connection succeeded (but it shouldn't work without auth)
            # Force check the connection state by trying to publish
            await publisher.publish("test.auth.fail", {"test": "should_fail"})
        except Exception:  # noqa: BLE001 - broad catch acceptable in integration test
            connection_failed = True

        # The connection should have failed OR health check should fail
        health_ok = await publisher.health_check()
        assert (
            connection_failed or not health_ok
        ), "Either connection should fail OR health check should fail when no auth provided to secured server"

        # Clean up
        await publisher.disconnect()

    finally:
        # Restore original environment variables
        for var, value in original_values.items():
            os.environ[var] = value
        # Clean up the test URL
        if "NATS_URL" in os.environ:
            del os.environ["NATS_URL"]
