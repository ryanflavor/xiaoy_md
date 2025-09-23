"""Integration test for live entrypoint: adapter → service → NATS via src.main.

AC coverage (Story 2.4.1):
- AC1: Live entry composes CTPGatewayAdapter + MarketDataService + NATSPublisher
- AC2: Respects NATS env vars and CTP_SYMBOL as initial target
- AC3: Logs NATS connection implicitly; we assert publish via real subscriber
- AC4: Does not modify src/__main__.py paths (indirectly validated by existing tests)
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from typing import Any

import nats
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.asyncio, pytest.mark.timeout(60)]


def _choose_port(preferred: int) -> int:
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
    name = "test-nats-live-ingest"
    subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)

    client_port = _choose_port(4226)
    monitor_port = _choose_port(8226)

    res = subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            name,
            "-p",
            f"{client_port}:4222",
            "-p",
            f"{monitor_port}:8222",
            "nats:latest",
            "-js",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if res.returncode != 0:
        # Keep exception message minimal to satisfy code style
        raise RuntimeError

    # Wait briefly for readiness
    start = time.time()
    ready = False
    while time.time() - start < 3.0:
        logs = subprocess.run(
            ["docker", "logs", name],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        ).stdout
        if "Server is ready" in logs or "Listening for client connections" in logs:
            ready = True
            break
        time.sleep(0.1)
    if not ready:
        diag_logs = subprocess.run(
            ["docker", "logs", name],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        ).stdout
        subprocess.run(["docker", "rm", "-f", name], check=False)
        pytest.skip(f"NATS did not become ready quickly. Logs:\n{diag_logs[-2000:]}")

    yield {"name": name, "client_port": client_port}

    subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)


@pytest.mark.timeout(30)
async def test_live_ingest_entrypoint_publishes_to_nats(nats_container):
    vt_symbol = "IF2312.CFFEX"
    base_symbol, exchange = vt_symbol.split(".", 1)
    expected_subject = f"market.tick.{exchange}.{base_symbol}"
    nats_url = f"nats://localhost:{nats_container['client_port']}"

    # Connect subscriber first to avoid missing early publish
    nc = await nats.connect(nats_url)
    received: dict[str, Any] | None = None
    ev = asyncio.Event()

    async def cb(msg):  # type: ignore[no-untyped-def]
        nonlocal received
        received = json.loads(msg.data.decode())
        ev.set()

    sub = await nc.subscribe(expected_subject, cb=cb)

    # Launch live entrypoint in subprocess with test connector
    env = {
        **os.environ,
        "MD_RUN_INGEST": "1",
        "MD_DURATION_SECONDS": "1",
        "CTP_SYMBOL": vt_symbol,
        "CTP_GATEWAY_CONNECT": "tests.integration.fake_ctp_connector:gateway_connect",
        "NATS_URL": nats_url,
        # Ensure code paths treat this as non-development for normal retry windows
        "ENVIRONMENT": "test",
        "PYTHONPATH": str(Path.cwd()),
    }

    # Use -m to run src.main
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "src.main",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=env,
    )

    # Wait for message or timeout
    try:
        await asyncio.wait_for(ev.wait(), timeout=5.0)
    except TimeoutError:
        logs = subprocess.run(
            ["docker", "logs", nats_container["name"]],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        ).stdout
        # Fetch some process output for diagnostics
        proc_out = b""
        if proc.stdout:
            with contextlib.suppress(Exception):  # best effort
                proc_out = await asyncio.wait_for(proc.stdout.read(), timeout=1.0)
        pytest.fail(
            f"Did not receive message on {expected_subject}.\n"
            f"NATS logs:\n{logs[-2000:]}\n"
            f"proc_out:\n{proc_out.decode(errors='ignore')[-2000:]}"
        )
    finally:
        with contextlib.suppress(Exception):
            await sub.unsubscribe()

    # Ensure payload looks correct enough (shape validated in other tests)
    assert received is not None
    assert received.get("symbol") == vt_symbol
    assert received.get("exchange") == exchange

    # Wait for process to exit (bounded)
    try:
        await asyncio.wait_for(proc.wait(), timeout=5.0)
    except TimeoutError:
        proc.kill()
        await proc.wait()

    await nc.close()
