#!/usr/bin/env python3
"""Request md.subscribe.bulk and save the response to logs/ with timestamp.

Usage examples:
  uv run python scripts/test_bulk_subscribe.py
  uv run python scripts/test_bulk_subscribe.py --symbols rb2510.SHFE IF2312.CFFEX --env-file .env

The script will create a file like:
  logs/bulk_subscribe_result-YYYYMMDD-HHMMSS.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import time
from typing import Any
from urllib.parse import urlparse


def _load_env(env_file: Path) -> None:
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        t = line.strip()
        if not t or t.startswith("#") or "=" not in t:
            continue
        k, v = t.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k in {"NATS_URL", "NATS_USER", "NATS_PASSWORD", "CTP_SYMBOL"}:
            os.environ[k] = v  # always override from .env for deterministic tests


def _normalize_nats_url(url: str) -> str:
    try:
        pu = urlparse(url)
        if pu.hostname == "nats":
            return "nats://127.0.0.1:4222"
    except ValueError:
        return "nats://127.0.0.1:4222"
    return url


async def _bulk_subscribe(
    symbols: list[str], nats_url: str, user: str | None, password: str | None
) -> str:
    import nats

    nc = (
        await nats.connect(nats_url, user=user, password=password)
        if user and password
        else await nats.connect(nats_url)
    )
    try:
        payload = json.dumps({"symbols": symbols}).encode()
        msg = await nc.request("md.subscribe.bulk", payload, timeout=10.0)
        return msg.data.decode()
    finally:
        await nc.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Save md.subscribe.bulk response to logs/"
    )
    parser.add_argument("--env-file", default=".env", help="Path to .env (optional)")
    parser.add_argument(
        "--nats-url",
        default=os.getenv("NATS_URL", "nats://127.0.0.1:4222"),
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
    parser.add_argument("--symbols", nargs="*", help="Symbols to subscribe (vt_symbol)")
    parser.add_argument(
        "--include-invalid",
        action="store_true",
        help="Include an invalid symbol (!!bad!!) to test rejection",
    )
    args = parser.parse_args(argv)

    # Always load .env first so we have credentials by default
    _load_env(Path(args.env_file))
    # Resolve connection parameters with precedence: CLI > .env > defaults
    nats_url = _normalize_nats_url(
        args.nats_url or os.getenv("NATS_URL", "nats://127.0.0.1:4222")
    )
    user = args.user if args.user is not None else os.getenv("NATS_USER")
    password = (
        args.password if args.password is not None else os.getenv("NATS_PASSWORD")
    )

    symbols: list[str]
    if args.symbols:
        symbols = list(dict.fromkeys(args.symbols))  # de-dup preserving order
    else:
        # Use CTP_SYMBOL and a common index future as defaults
        sym1 = os.getenv("CTP_SYMBOL") or "au2512.SHFE"
        sym2 = "IF2312.CFFEX"
        symbols = [sym1, sym2]
    if args.include_invalid:
        symbols.append("!!bad!!")

    data = asyncio.run(_bulk_subscribe(symbols, nats_url, user, password))

    ts = time.strftime("%Y%m%d-%H%M%S")
    Path("logs").mkdir(parents=True, exist_ok=True)
    out = Path("logs") / f"bulk_subscribe_result-{ts}.json"
    try:
        obj: Any = json.loads(data)
        out.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    except json.JSONDecodeError:
        out.write_text(data, encoding="utf-8")

    print(str(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
