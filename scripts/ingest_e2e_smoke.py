#!/usr/bin/env python3
"""End-to-end ingest smoke: src.main publishes to NATS, subscriber receives.

Starts a temporary NATS container (no auth), runs live ingest for ~1s using
the fake test connector, subscribes to the expected subject, and records
results to JSON and a short log file under a writable directory.

Usage:
  uv run python scripts/ingest_e2e_smoke.py
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

NATS_READY_TIMEOUT = 5.0


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


def _choose_output_dir() -> Path:
    candidates = [Path("logs"), Path(".logs"), Path("e2e_results"), Path.cwd()]
    for p in candidates:
        try:
            p.mkdir(parents=True, exist_ok=True)
            t = p / ".write_test"
            t.write_text("ok")
            t.unlink(missing_ok=True)
        except OSError:
            continue
        else:
            return p
    return Path.cwd()


async def _amain() -> int:  # noqa: PLR0915 - orchestration script with sequential steps
    name = "md-e2e-smoke"
    # Ensure clean slate
    subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)

    client_port = _choose_port(43222)
    monitor_port = _choose_port(48222)

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
        print(
            json.dumps(
                {"ok": False, "step": "docker_run", "stderr": res.stderr[-2000:]}
            )
        )
        return 2

    # Wait for readiness
    start = time.time()
    ready = False
    while time.time() - start < NATS_READY_TIMEOUT:
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
        print(
            json.dumps(
                {"ok": False, "step": "nats_ready", "logs_tail": diag_logs[-2000:]}
            )
        )
        subprocess.run(["docker", "rm", "-f", name], check=False)
        return 3

    # Async test body
    import nats

    vt_symbol = "IF2312.CFFEX"
    base_symbol, exchange = vt_symbol.split(".", 1)
    subject = f"market.tick.{exchange}.{base_symbol}"
    url = f"nats://localhost:{client_port}"

    nc = await nats.connect(url)
    received: dict[str, Any] | None = None
    ev = asyncio.Event()

    async def _cb(msg):  # type: ignore[no-untyped-def]
        nonlocal received
        try:
            received = json.loads(msg.data.decode() or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            received = {"decode_error": True}
        ev.set()

    sub = await nc.subscribe(subject, cb=_cb)

    env = {
        **os.environ,
        "MD_RUN_INGEST": "1",
        "MD_DURATION_SECONDS": "1",
        "CTP_SYMBOL": vt_symbol,
        "CTP_GATEWAY_CONNECT": "tests.integration.fake_ctp_connector:gateway_connect",
        "NATS_URL": url,
        "ENVIRONMENT": "test",
        "PYTHONPATH": str(Path.cwd()),
    }

    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "src.main",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=env,
    )

    ok = True
    reason = None
    try:
        await asyncio.wait_for(ev.wait(), timeout=5.0)
    except TimeoutError:
        ok = False
        reason = "timeout_waiting_message"
    finally:
        with contextlib.suppress(Exception):
            await sub.unsubscribe()
        with contextlib.suppress(Exception):
            await nc.close()
        with contextlib.suppress(Exception):
            await asyncio.wait_for(proc.wait(), timeout=3.0)
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)

    # Write results
    out_dir = _choose_output_dir()
    ts = time.strftime("%Y%m%d-%H%M%S")
    json_path = out_dir / f"ingest-e2e-smoke-{ts}.json"
    log_path = out_dir / f"ingest-e2e-smoke-{ts}.log"
    result = {
        "ok": ok,
        "subject": subject,
        "received": received,
        "nats_url": url,
        "container": name,
        "reason": reason,
    }
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    lines = [
        f"Ingest E2E Smoke — URL: {url}",
        f"Subject: {subject}",
        f"Overall: {'OK' if ok else 'FAIL'}",
        f"Reason: {reason or ''}",
        f"Received: {json.dumps(received or {}, ensure_ascii=False)}",
    ]
    log_path.write_text("\n".join(lines))
    print(
        json.dumps(
            {"ok": ok, "json": str(json_path), "log": str(log_path)}, ensure_ascii=False
        )
    )
    return 0 if ok else 4


def main() -> int:
    try:
        return asyncio.run(_amain())
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
