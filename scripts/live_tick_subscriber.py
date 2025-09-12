#!/usr/bin/env python3
"""Subscribe to LIVE ticks on NATS and print a few messages.

Usage examples:
  uv run python scripts/live_tick_subscriber.py
  uv run python scripts/live_tick_subscriber.py --nats-url nats://localhost:4222 --count 10 --timeout 90

Environment variables (used by default):
  NATS_URL, NATS_USER, NATS_PASSWORD
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from typing import Any


async def _subscribe(
    nats_url: str, user: str | None, password: str | None, count: int, timeout: float
) -> list[str]:
    import nats  # Imported lazily to keep script lightweight

    nc = (
        await nats.connect(nats_url, user=user, password=password)
        if (user and password)
        else await nats.connect(nats_url)
    )
    lines: list[str] = []
    got = 0
    done = asyncio.Event()

    async def cb(msg: Any) -> None:
        nonlocal got
        data: dict[str, Any]
        try:
            data = json.loads(msg.data.decode())
        except json.JSONDecodeError:
            data = {"raw": msg.data.decode(errors="ignore")}
        lines.append(
            json.dumps({"subject": msg.subject, "data": data}, ensure_ascii=False)
        )
        got += 1
        if got >= count:
            done.set()
            await nc.close()

    await nc.subscribe("market.tick.>", cb=cb)
    try:
        await asyncio.wait_for(done.wait(), timeout=timeout)
    except TimeoutError:
        # Timeout is fine; close and return what we got
        pass
    finally:
        if not nc.is_closed:
            await nc.close()
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Subscribe to live ticks from NATS and print a few messages."
    )
    parser.add_argument(
        "--nats-url",
        default=os.getenv("NATS_URL", "nats://localhost:4222"),
        help="NATS URL",
    )
    parser.add_argument(
        "--user", default=os.getenv("NATS_USER"), help="NATS username (optional)"
    )
    parser.add_argument(
        "--password",
        default=os.getenv("NATS_PASSWORD"),
        help="NATS password (optional)",
    )
    parser.add_argument(
        "--count", type=int, default=5, help="Number of messages to print before exit"
    )
    parser.add_argument(
        "--timeout", type=float, default=60.0, help="Max seconds to wait for messages"
    )
    args = parser.parse_args(argv)

    lines = asyncio.run(
        _subscribe(args.nats_url, args.user, args.password, args.count, args.timeout)
    )
    if lines:
        print("\n".join(lines))
        return 0
    print("(no subscriber output)")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
