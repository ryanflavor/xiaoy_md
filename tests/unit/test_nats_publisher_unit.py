from __future__ import annotations

import json

import pytest

from src.config import AppSettings
from src.infrastructure.nats_publisher import NATSPublisher


class _FakeNATS:
    def __init__(self) -> None:
        self.published: list[tuple[str, bytes]] = []

    async def publish(
        self, subject: str, data: bytes
    ) -> None:  # pragma: no cover - exercised in test
        self.published.append((subject, data))


@pytest.mark.asyncio
async def test_nats_publisher_publish_calls_client_with_json_payload() -> None:
    settings = AppSettings()
    pub = NATSPublisher(settings)

    # Bypass real connection
    fake = _FakeNATS()
    pub.nc_client = fake
    pub.connected = True

    data = {"symbol": "IF2312.CFFEX", "exchange": "CFFEX", "price": "100"}
    subject = "market.tick.CFFEX.IF2312"

    await pub.publish(subject, data)

    assert len(fake.published) == 1
    sub, payload = fake.published[0]
    assert sub == subject
    # Payload must be JSON-encoded
    decoded = json.loads(payload.decode())
    assert decoded["symbol"] == "IF2312.CFFEX"
    assert decoded["exchange"] == "CFFEX"
