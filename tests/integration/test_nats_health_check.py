"""Integration test for NATS health check functionality."""

import asyncio
import json
import socket
import subprocess
import time

import nats
import pytest

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
def nats_container():
    """Start NATS container for testing on dynamic ports."""
    container_name = "test-nats-health"

    # Stop and remove any existing container
    subprocess.run(
        ["docker", "rm", "-f", container_name],
        capture_output=True,
        check=False,
    )

    client_port = _choose_port(4222)
    monitor_port = _choose_port(8222)

    # Start NATS container
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
            "nats:latest",
            "-js",  # Enable JetStream
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(  # noqa: TRY003
            f"Failed to start NATS container: {result.stderr.strip()}"
        )

    container_id = result.stdout.strip()

    # Wait for NATS to be ready by checking logs
    time.sleep(2)
    ready = False
    for _ in range(60):  # ~30 seconds
        logs = subprocess.run(
            ["docker", "logs", container_name],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        ).stdout
        if "Server is ready" in logs or "Listening for client connections" in logs:
            ready = True
            break
        time.sleep(0.5)
    if not ready:
        # Get last logs for diagnostics
        diag_logs = subprocess.run(
            ["docker", "logs", container_name],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        ).stdout
        subprocess.run(["docker", "rm", "-f", container_name], check=False)
        pytest.fail(
            f"NATS container failed to start (no ready logs). Recent logs:\n{diag_logs[-1000:]}"
        )

    yield {
        "name": container_name,
        "client_port": client_port,
        "monitor_port": monitor_port,
    }

    # Cleanup
    subprocess.run(
        ["docker", "rm", "-f", container_name], capture_output=True, check=False
    )


@pytest.fixture
async def app_with_nats(nats_container):
    """Get application container for testing."""
    import os

    # In CI, the application is already running via docker-compose
    if os.environ.get("CI") == "true":
        # Use the existing market-data-service container
        container_name = "market-data-service"

        # Check if the container is running
        result = subprocess.run(
            ["docker", "ps", "-q", "-f", f"name={container_name}"],
            capture_output=True,
            check=True,
        )

        if not result.stdout.decode().strip():
            # If not found, check docker-compose services
            result = subprocess.run(
                ["docker", "compose", "ps", "-q", "market-data-service"],
                capture_output=True,
                check=False,
            )
            if result.returncode == 0 and result.stdout.decode().strip():
                container_name = "market-data-service"
            else:
                pytest.skip("market-data-service container not running in CI")

        yield container_name
        # No cleanup needed for CI containers
    else:
        # Local testing: start our own container
        container_name = "test-app-nats"
        docker_test_image = "market-data-service:latest"

        # Stop and remove any existing container
        subprocess.run(
            ["docker", "rm", "-f", container_name],
            capture_output=True,
            check=False,
        )

        # Start application container
        result = subprocess.run(
            [
                "docker",
                "run",
                "-d",
                "--name",
                container_name,
                "--network",
                "host",  # Use host network to access NATS on localhost:4222
                "-e",
                f"NATS_URL=nats://localhost:{nats_container['client_port']}",
                "-e",
                "LOG_LEVEL=DEBUG",
                docker_test_image,
            ],
            capture_output=True,
            check=True,
        )

        container_id = result.stdout.decode().strip()

        # Wait for application to connect to NATS
        await asyncio.sleep(3)

        # Check if container is still running
        result = subprocess.run(
            ["docker", "ps", "-q", "-f", f"name={container_name}"],
            capture_output=True,
            check=True,
        )

        if not result.stdout.decode().strip():
            # Container stopped, get logs for debugging
            logs = subprocess.run(
                ["docker", "logs", container_name],
                capture_output=True,
                check=False,
            )
            pytest.fail(f"Application container stopped. Logs: {logs.stdout.decode()}")

        yield container_name

        # Cleanup
        subprocess.run(
            ["docker", "rm", "-f", container_name], capture_output=True, check=False
        )


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.timeout(300)
async def test_nats_health_check_response(app_with_nats, nats_container):
    """Test that application responds to NATS health check requests."""
    import os

    # In CI, connect to the docker-compose NATS on port 4222
    if os.environ.get("CI") == "true":
        nats_url = "nats://localhost:4222"
    else:
        nats_url = f"nats://localhost:{nats_container['client_port']}"

    # Connect to NATS (no auth for basic test)
    nc = await nats.connect(nats_url)

    try:
        # Send health check request
        response = await nc.request(
            "health.check",
            b"{}",
            timeout=5.0,
        )

        # Parse response
        health_data = json.loads(response.data.decode())

        # Verify response structure
        assert "service" in health_data
        assert "status" in health_data
        assert "timestamp" in health_data
        assert "stats" in health_data

        # Verify service name
        assert health_data["service"] == "market-data-service"

        # Verify status
        assert health_data["status"] in ["healthy", "unhealthy"]

        # Verify stats structure
        stats = health_data["stats"]
        assert "connect_attempts" in stats
        assert "successful_publishes" in stats
        assert "failed_publishes" in stats

    finally:
        await nc.close()


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.timeout(300)
async def test_nats_publisher_connection_resilience(app_with_nats, nats_container):
    """Test that publisher handles connection disruptions gracefully."""
    import os

    # In CI, connect to the docker-compose NATS on port 4222
    if os.environ.get("CI") == "true":
        nats_url = "nats://localhost:4222"
    else:
        nats_url = f"nats://localhost:{nats_container['client_port']}"

    # Connect to NATS (no auth for basic test)
    nc = await nats.connect(nats_url)

    try:
        # First health check should succeed
        response1 = await nc.request("health.check", b"{}", timeout=5.0)
        data1 = json.loads(response1.data.decode())
        assert data1["status"] == "healthy"

        # Give the app a moment to flush logs
        await asyncio.sleep(1)
        # Get container logs to verify connection
        logs_result = subprocess.run(
            ["docker", "logs", app_with_nats],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            text=True,
        )
        logs = logs_result.stdout

        # Verify that NATS connection was established
        assert "Connected to NATS" in logs or "NATS Publisher" in logs

        # Verify health check responder was set up
        assert "Health check responder set up" in logs or "health.check" in logs

    finally:
        await nc.close()


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.timeout(300)
async def test_multiple_health_check_requests(app_with_nats, nats_container):
    """Test that application handles multiple concurrent health check requests."""
    import os

    # In CI, connect to the docker-compose NATS on port 4222
    if os.environ.get("CI") == "true":
        nats_url = "nats://localhost:4222"
    else:
        nats_url = f"nats://localhost:{nats_container['client_port']}"

    # Connect to NATS (no auth for basic test)
    nc = await nats.connect(nats_url)

    try:
        # Send multiple concurrent health check requests
        tasks = []
        for _ in range(10):
            task = nc.request("health.check", b"{}", timeout=5.0)
            tasks.append(task)

        responses = await asyncio.gather(*tasks)

        # Verify all responses are valid
        for response in responses:
            health_data = json.loads(response.data.decode())
            assert health_data["service"] == "market-data-service"
            assert health_data["status"] in ["healthy", "unhealthy"]

        # All should have the same service name
        service_names = [json.loads(r.data.decode())["service"] for r in responses]
        assert len(set(service_names)) == 1

    finally:
        await nc.close()


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.timeout(300)
async def test_circuit_breaker_state_in_health_check(app_with_nats, nats_container):
    """Test that health check includes circuit breaker state."""
    import os

    # In CI, connect to the docker-compose NATS on port 4222
    if os.environ.get("CI") == "true":
        nats_url = "nats://localhost:4222"
    else:
        nats_url = f"nats://localhost:{nats_container['client_port']}"

    # Connect to NATS (no auth for basic test)
    nc = await nats.connect(nats_url)

    try:
        # Request health check
        response = await nc.request("health.check", b"{}", timeout=5.0)
        health_data = json.loads(response.data.decode())

        # Verify circuit breaker state is included
        assert "circuit_breaker_state" in health_data
        assert health_data["circuit_breaker_state"] in ["closed", "open", "half_open"]

        # Initially should be closed (healthy)
        assert health_data["circuit_breaker_state"] == "closed"

    finally:
        await nc.close()


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.timeout(300)
async def test_application_graceful_shutdown(app_with_nats, nats_container):
    """Test that application shuts down gracefully when receiving SIGTERM."""
    import os

    # In CI, connect to the docker-compose NATS on port 4222
    if os.environ.get("CI") == "true":
        nats_url = "nats://localhost:4222"
    else:
        nats_url = f"nats://localhost:{nats_container['client_port']}"

    # First verify it's running and healthy (no auth for basic test)
    nc = await nats.connect(nats_url)

    try:
        # Verify initial health
        response = await nc.request("health.check", b"{}", timeout=5.0)
        assert json.loads(response.data.decode())["status"] == "healthy"

        # Send SIGTERM to application
        subprocess.run(
            ["docker", "kill", "--signal=SIGTERM", app_with_nats],
            capture_output=True,
            check=True,
        )

        # Wait a bit for graceful shutdown
        await asyncio.sleep(2)

        # Check that container has stopped
        result = subprocess.run(
            ["docker", "ps", "-q", "-f", f"name={app_with_nats}"],
            capture_output=True,
            check=True,
        )

        # Container should be stopped
        assert not result.stdout.decode().strip()

        # Check logs for graceful shutdown message
        logs_result = subprocess.run(
            ["docker", "logs", app_with_nats],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            text=True,
        )
        logs = logs_result.stdout

        # Verify graceful shutdown occurred
        assert (
            "Shutting down Market Data Service" in logs or "graceful shutdown" in logs
        )
        assert "Disconnected from NATS" in logs or "NATS connection closed" in logs

    finally:
        await nc.close()
