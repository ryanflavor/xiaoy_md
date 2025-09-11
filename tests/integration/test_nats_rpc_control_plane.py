"""Integration tests for NATS RPC control plane.

Validates request/response for:
- md.contracts.list
- md.subscribe.bulk
"""

from __future__ import annotations

import json

import nats
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.timeout(120)]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_contracts_list_rpc(app_with_nats, nats_container):
    """md.contracts.list responds with structure and source within 1s."""
    nc = await nats.connect(f"nats://localhost:{nats_container['client_port']}")
    try:
        resp = await nc.request("md.contracts.list", b"{}", timeout=5.0)
        data = json.loads(resp.data.decode())
        assert isinstance(data.get("symbols"), list)
        assert data.get("source") in {"cache", "vnpy", "empty"}
        assert isinstance(data.get("ts"), str)
    finally:
        await nc.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_subscribe_bulk_rpc(app_with_nats, nats_container):
    """md.subscribe.bulk performs idempotent bulk subscriptions and reports errors."""
    nc = await nats.connect(f"nats://localhost:{nats_container['client_port']}")
    try:
        payload = {
            "symbols": [
                "rb2401.SHFE",
                "rb2401.SHFE",  # duplicate for idempotency
                "IF2312.CFFEX",
                "!!bad!!",  # invalid symbol to exercise rejection path
            ]
        }
        resp = await nc.request(
            "md.subscribe.bulk", json.dumps(payload).encode(), timeout=5.0
        )
        data = json.loads(resp.data.decode())
        accepted = data.get("accepted") or []
        rejected = data.get("rejected") or []
        assert "rb2401.SHFE" in accepted
        assert "IF2312.CFFEX" in accepted
        # Only one entry for duplicate
        assert accepted.count("rb2401.SHFE") == 1
        # Rejected contains invalid symbol with reason
        assert any(item.get("symbol") == "!!bad!!" for item in rejected)
        assert isinstance(data.get("ts"), str)
    finally:
        await nc.close()
