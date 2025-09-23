#!/usr/bin/env python3
"""Downstream example: consume market ticks from NATS and write JSONL.

Usage:
  uv run python scripts/consumers/tick_jsonl_consumer.py \
    --nats-url nats://127.0.0.1:4222 \
    --user "$NATS_USER" --password "$NATS_PASSWORD" \
    --subject market.tick.> \
    --out logs/downstream/ticks-$(date +%Y%m%d-%H%M%S).jsonl

Notes:
  - Uses NATS core subscribe (no JetStream). Suitable for live fan-out.
  - Writes one JSON object per line: {subject, data, received_at}.
  - Ctrl+C to stop. Use --max to stop after N messages.

"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import os
from pathlib import Path
from typing import Any


def _load_env_defaults() -> None:
    # If no CLI args provided, honor env and fallback to .env if present
    if os.getenv("NATS_URL") and (os.getenv("NATS_USER") or os.getenv("NATS_PASSWORD")):
        return
    env_file = Path.cwd() / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        t = line.strip()
        if not t or t.startswith("#") or "=" not in t:
            continue
        k, v = t.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k in {"NATS_URL", "NATS_USER", "NATS_PASSWORD"} and not os.getenv(k):
            os.environ[k] = v


Credentials = tuple[str | None, str | None]


@dataclass(slots=True)
class ConsumerLimits:
    max_messages: int | None = None
    flush_every: int = 0


async def run_consumer(
    nats_url: str,
    subject: str,
    out_path: Path,
    *,
    credentials: Credentials | None = None,
    limits: ConsumerLimits | None = None,
) -> int:
    from nats.aio.client import Client as NatsClient

    out_path.parent.mkdir(parents=True, exist_ok=True)
    f = out_path.open("a", encoding="utf-8")

    nc = NatsClient()
    opts: dict[str, Any] = {"servers": [nats_url], "name": "tick-jsonl-consumer"}
    if credentials:
        user, password = credentials
        if user and password:
            opts.update({"user": user, "password": password})
    await nc.connect(**opts)

    count = 0
    done = asyncio.Event()

    effective_limits = limits or ConsumerLimits()

    async def cb(msg):  # type: ignore[no-untyped-def]
        nonlocal count
        received_at = datetime.now(UTC).isoformat()
        try:
            payload = json.loads(msg.data.decode() or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = {"raw": msg.data.decode(errors="ignore")}
        obj = {"subject": msg.subject, "data": payload, "received_at": received_at}
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")
        count += 1
        flush_every = effective_limits.flush_every
        if flush_every > 0 and (count % flush_every) == 0:
            f.flush()
        if (
            effective_limits.max_messages is not None
            and count >= effective_limits.max_messages
        ):
            done.set()

    sub = await nc.subscribe(subject, cb=cb)
    try:
        await done.wait()
    finally:
        await sub.unsubscribe()
        await nc.drain()
        await nc.close()
        f.flush()
        f.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Consume market ticks and write JSONL")
    _load_env_defaults()
    p.add_argument("--nats-url", default=os.getenv("NATS_URL", "nats://127.0.0.1:4222"))
    p.add_argument("--user", default=os.getenv("NATS_USER"))
    p.add_argument("--password", default=os.getenv("NATS_PASSWORD"))
    p.add_argument("--subject", default="market.tick.>")
    p.add_argument(
        "--out",
        default=f"logs/downstream/ticks-{datetime.now().strftime('%Y%m%d-%H%M%S')}.jsonl",
        help="Output JSONL file path",
    )
    p.add_argument(
        "--max", type=int, default=0, help="Stop after N messages (0=run until Ctrl+C)"
    )
    p.add_argument("--flush-every", type=int, default=100, help="Flush every N lines")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    max_messages = int(args.max or 0) or None
    try:
        return asyncio.run(
            run_consumer(
                args.nats_url,
                args.subject,
                Path(args.out),
                credentials=(args.user, args.password),
                limits=ConsumerLimits(
                    max_messages=max_messages,
                    flush_every=int(args.flush_every or 0),
                ),
            )
        )
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
