from __future__ import annotations

import json

from pydantic import SecretStr
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


def test_nats_publisher_connection_options_unwraps_secret_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for var in ("NATS_USER", "NATS_PASSWORD", "NATS_URL"):
        monkeypatch.delenv(var, raising=False)

    settings = type(
        "Settings",
        (),
        {
            "nats_url": "nats://localhost:4222",
            "nats_user": "user",
            "nats_password": SecretStr("topsecret"),  # pragma: allowlist secret
            "nats_client_id": "client",
            "environment": "development",
            "app_name": "test-app",
            "nats_health_check_subject": "health.check",
        },
    )()

    pub = NATSPublisher(settings)
    options = pub.create_connection_options()

    assert options["user"] == "user"
    assert options["password"] == "topsecret"  # pragma: allowlist secret
