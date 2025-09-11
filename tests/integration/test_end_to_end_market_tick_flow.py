"""End-to-end test: vnpy-like tick → adapter → service → NATS.

AC coverage:
- AC1: Starts full composition in-process (adapter+service+publisher)
- AC2: Emits known TickData via injected gateway function
- AC3: Uses real NATS subscriber (no auth) and expected subject
- AC4: Asserts subscriber receives expected data shape and values

- Subject naming scheme: market.tick.{exchange}.{symbol}
- Timezone policy: serialized timestamps must include +08:00 (Asia/Shanghai)
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from datetime import datetime
import json
import socket
import subprocess
import time
from typing import Any

import nats
import pytest

from src.application.services import MarketDataService
from src.config import AppSettings
from src.infrastructure.ctp_adapter import CTPGatewayAdapter
from src.infrastructure.nats_publisher import NATSPublisher

pytestmark = [pytest.mark.integration, pytest.mark.asyncio, pytest.mark.timeout(60)]


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
    """Start NATS container for testing on dynamic ports (no auth)."""
    container_name = "test-nats-e2e"

    # Stop and remove any existing container
    subprocess.run(
        ["docker", "rm", "-f", container_name], capture_output=True, check=False
    )

    client_port = _choose_port(4222)
    monitor_port = _choose_port(8222)

    # Start NATS container (JetStream enabled)
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
            "-js",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(  # noqa: TRY003
            f"Failed to start NATS container: {result.stderr.strip()}"
        )

    # Wait for NATS to be ready quickly (≤ 3s target)
    ready = False
    start = time.time()
    while time.time() - start < 3.0:
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
        time.sleep(0.1)
    if not ready:
        diag_logs = subprocess.run(
            ["docker", "logs", container_name],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        ).stdout
        subprocess.run(["docker", "rm", "-f", container_name], check=False)
        pytest.fail(
            f"NATS container failed to start within 3s. Recent logs:\n{diag_logs[-2000:]}"
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


@dataclass
class _StubTick:
    """Minimal vnpy-like TickData for adapter.on_tick."""

    symbol: str
    last_price: float
    volume: int
    datetime: datetime
    bid_price_1: float
    ask_price_1: float


def _build_stub_tick(vt_symbol: str) -> _StubTick:
    from zoneinfo import ZoneInfo

    china_tz = ZoneInfo("Asia/Shanghai")
    dt = datetime(2025, 1, 1, 9, 30, 0, tzinfo=china_tz)
    return _StubTick(
        symbol=vt_symbol,
        last_price=1234.5,
        volume=10,
        datetime=dt,
        bid_price_1=1234.4,
        ask_price_1=1234.6,
    )


async def _subscribe_and_wait(nc, subject: str, timeout: float = 5.0) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    received: dict[str, Any] | None = None
    ev = asyncio.Event()

    async def cb(msg):  # type: ignore[no-untyped-def]
        nonlocal received
        received = json.loads(msg.data.decode())
        ev.set()

    sub = await nc.subscribe(subject, cb=cb)
    await asyncio.wait_for(ev.wait(), timeout=timeout)
    with contextlib.suppress(Exception):
        await sub.unsubscribe()

    assert received is not None
    return received


@pytest.mark.timeout(30)
async def test_end_to_end_market_tick_flow(nats_container):
    # Arrange: expected routing and vnpy-like tick
    base_symbol = "IF2312"
    exchange = "CFFEX"
    vt_symbol = f"{base_symbol}.{exchange}"
    expected_subject = f"market.tick.{exchange}.{base_symbol}"

    stub_tick = _build_stub_tick(vt_symbol)

    # Compose in-process service graph with ephemeral NATS
    nats_url = f"nats://localhost:{nats_container['client_port']}"
    settings = AppSettings(
        nats_url=nats_url, nats_client_id="e2e-md-tester", environment="test"
    )

    publisher = NATSPublisher(settings)
    # Inject gateway function that emits exactly one tick from the session thread
    adapter_ref: dict[str, CTPGatewayAdapter] = {}

    def gateway_connect(_setting: dict[str, Any], _should_shutdown) -> None:
        # AC2: emit known tick via adapter.on_tick from worker thread
        adapter_ref["adapter"].on_tick(stub_tick)
        # Return to end the session thread cleanly

    adapter = CTPGatewayAdapter(settings, gateway_connect=gateway_connect)
    adapter_ref["adapter"] = adapter

    # Seed contract map so on_tick is accepted (base and vt symbol for robustness)
    adapter.symbol_contract_map[base_symbol] = object()
    adapter.symbol_contract_map[vt_symbol] = object()

    service = MarketDataService(market_data_port=adapter, publisher_port=publisher)

    # Act
    nc = await nats.connect(nats_url)
    await publisher.connect()
    await adapter.connect()
    proc_task = asyncio.create_task(service.process_market_data())

    try:
        received = await _subscribe_and_wait(nc, expected_subject, timeout=5.0)
    except TimeoutError:
        logs = subprocess.run(
            ["docker", "logs", nats_container["name"]],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        ).stdout
        pytest.fail(
            f"Did not receive message on {expected_subject}. NATS logs:\n{logs[-2000:]}"
        )
        return

    # Assert payload key fields (AC4)
    assert received["symbol"] == vt_symbol
    assert received["exchange"] == exchange
    assert received["timestamp"].endswith("+08:00")
    # Numeric fields serialized as strings
    assert isinstance(received.get("price"), str)
    assert isinstance(received.get("bid"), str)
    assert isinstance(received.get("ask"), str)
    if received.get("volume") is not None:
        assert isinstance(received.get("volume"), str)

    # Teardown: stop processing and close connections
    proc_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await proc_task

    await adapter.disconnect()
    await publisher.disconnect()
    await nc.close()
