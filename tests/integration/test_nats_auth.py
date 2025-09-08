"""Integration tests for NATS authentication."""

import subprocess
import time

import nats
from nats.errors import NoServersError
import pytest


@pytest.fixture(scope="module")
def nats_auth_container():
    """Start NATS container with authentication enabled."""
    container_name = "test-nats-auth"

    # Stop and remove any existing container
    subprocess.run(
        ["docker", "rm", "-f", container_name],
        capture_output=True,
        check=False,
    )

    # Start NATS container with auth config
    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            container_name,
            "-p",
            "4225:4222",
            "-p",
            "8225:8222",
            "-v",
            f"{subprocess.run(['pwd'], capture_output=True, text=True, check=False).stdout.strip()}/config/nats-server.conf:/etc/nats/nats-server.conf:ro",
            "nats:latest",
            "-c",
            "/etc/nats/nats-server.conf",
        ],
        check=True,
    )

    # Wait for NATS to be ready
    time.sleep(3)

    yield container_name

    # Cleanup
    subprocess.run(["docker", "rm", "-f", container_name], check=False)


@pytest.mark.asyncio
async def test_connection_with_valid_credentials(nats_auth_container):
    """Test that connection succeeds with valid credentials."""
    nc = await nats.connect(
        "nats://localhost:4225",
        user="testuser",  # pragma: allowlist secret
        password="testpass",  # pragma: allowlist secret
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
            "nats://localhost:4225",
            error_cb=error_cb,
        )


@pytest.mark.asyncio
async def test_connection_with_invalid_credentials_fails(nats_auth_container):
    """Test that connection fails with invalid credentials."""

    async def error_cb(e):
        pass  # Suppress error logs

    with pytest.raises(NoServersError):
        await nats.connect(
            "nats://localhost:4225",
            user="wronguser",  # pragma: allowlist secret
            password="wrongpass",  # pragma: allowlist secret
            error_cb=error_cb,
        )


@pytest.mark.asyncio
async def test_connection_with_wrong_password_fails(nats_auth_container):
    """Test that connection fails with correct user but wrong password."""

    async def error_cb(e):
        pass  # Suppress error logs

    with pytest.raises(NoServersError):
        await nats.connect(
            "nats://localhost:4225",
            user="testuser",  # pragma: allowlist secret
            password="wrongpass",  # pragma: allowlist secret
            error_cb=error_cb,
        )


@pytest.mark.asyncio
async def test_multiple_users_can_connect(nats_auth_container):
    """Test that multiple configured users can connect."""
    # Connect as testuser
    nc1 = await nats.connect(
        "nats://localhost:4225",
        user="testuser",  # pragma: allowlist secret
        password="testpass",  # pragma: allowlist secret
    )
    assert nc1.is_connected

    # Connect as admin
    nc2 = await nats.connect(
        "nats://localhost:4225",
        user="admin",  # pragma: allowlist secret
        password="testpass",  # pragma: allowlist secret
    )
    assert nc2.is_connected

    # Both should be able to communicate
    sub = await nc1.subscribe("cross.talk")
    await nc2.publish("cross.talk", b"admin message")

    msg = await sub.next_msg(timeout=1)
    assert msg.data == b"admin message"

    await nc1.close()
    await nc2.close()


@pytest.mark.asyncio
async def test_nats_publisher_with_authentication():
    """Test NATSPublisher with authentication configured."""
    import os

    from src.config import AppSettings
    from src.infrastructure.nats_publisher import NATSPublisher

    # Set auth environment variables
    os.environ["NATS_URL"] = "nats://localhost:4225"
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
async def test_nats_publisher_without_auth_fails():
    """Test NATSPublisher fails to connect without auth to secured server."""
    import os

    from src.config import AppSettings
    from src.infrastructure.nats_publisher import NATSPublisher

    # Set URL without auth credentials
    os.environ["NATS_URL"] = "nats://localhost:4225"

    settings = AppSettings()
    publisher = NATSPublisher(settings)

    # Connect should fail without auth
    with pytest.raises(Exception):  # Will be wrapped in publisher's error handling
        await publisher.connect()

    assert not await publisher.health_check()

    # Clean up
    await publisher.disconnect()
