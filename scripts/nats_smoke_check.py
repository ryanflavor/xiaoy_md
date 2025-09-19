#!/usr/bin/env python3
"""NATS smoke test: detect local NATS, verify connect + pub/sub round-trip.

Outputs result JSON and a brief log under `logs/`.

Usage:
  uv run python scripts/nats_smoke_check.py [--nats-url nats://host:port]
  # or rely on auto-detection of a running `nats` container
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import subprocess
import time
from typing import Any
import uuid


@dataclass
class Result:
    ok: bool
    nats_url: str
    detected: dict[str, Any]
    steps: list[dict[str, Any]]
    duration_ms: int


def _detect_nats_url() -> tuple[str, dict[str, Any]]:
    # Priority 1: env / cli
    env = os.environ.get("NATS_URL")
    if env:
        return env, {"source": "env", "url": env}

    # Priority 2: docker ps | image contains "nats"
    try:
        out = (
            subprocess.run(
                ["docker", "ps", "--format", "{{.ID}}\t{{.Image}}\t{{.Names}}"],
                capture_output=True,
                text=True,
                check=False,
            )
            .stdout.strip()
            .splitlines()
        )
        for line in out:
            cid, image, name = ([*line.split("\t", 2), ""])[:3]
            if "nats" in image.lower() or "nats" in name.lower():
                port = subprocess.run(
                    ["docker", "port", cid, "4222/tcp"],
                    capture_output=True,
                    text=True,
                    check=False,
                ).stdout.strip()
                if port:
                    # Example: 0.0.0.0:4222\n:::4222
                    hostport = port.splitlines()[0].split("->")[-1].strip()
                    if ":" in hostport:
                        host, p = hostport.rsplit(":", 1)
                        # Some docker outputs use 0.0.0.0 or :::
                        url = f"nats://localhost:{p}"
                        return url, {
                            "source": "docker",
                            "container": name,
                            "image": image,
                            "hostport": hostport,
                            "url": url,
                        }
    except (OSError, subprocess.SubprocessError):
        pass

    return "nats://localhost:4222", {
        "source": "default",
        "url": "nats://localhost:4222",
    }


async def _smoke(
    nats_url: str, user: str | None, password: str | None
) -> list[dict[str, Any]]:
    from nats import errors as nats_errors
    from nats.aio.client import Client as NatsClient

    steps: list[dict[str, Any]] = []
    start = time.perf_counter()
    nc = NatsClient()

    # Connect
    try:
        opts: dict[str, Any] = {"servers": [nats_url], "name": "nats-smoke-check"}
        if user and password:
            opts.update({"user": user, "password": password})
        await nc.connect(**opts)
        steps.append({"step": "connect", "ok": True})
    except (nats_errors.Error, OSError) as exc:
        steps.append({"step": "connect", "ok": False, "error": str(exc)})
        return steps

    # Pub/Sub round-trip
    subject = f"smoke.test.{uuid.uuid4().hex[:8]}"
    payload = {"event": "smoke", "ts": time.time()}
    got: dict[str, Any] | None = None
    ev = asyncio.Event()

    async def _cb(msg):  # type: ignore[no-untyped-def]
        nonlocal got
        try:
            got = json.loads(msg.data.decode() or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            got = {"decode_error": True}
        ev.set()

    sub = await nc.subscribe(subject, cb=_cb)
    try:
        await nc.publish(subject, json.dumps(payload).encode())
        try:
            await asyncio.wait_for(ev.wait(), timeout=2.0)
        except TimeoutError:
            steps.append(
                {"step": "pubsub", "ok": False, "reason": "timeout", "subject": subject}
            )
        else:
            steps.append(
                {"step": "pubsub", "ok": True, "subject": subject, "received": got}
            )
    finally:
        await sub.unsubscribe()

    # Close
    try:
        await nc.drain()
        await nc.close()
        steps.append(
            {
                "step": "close",
                "ok": True,
                "elapsed_ms": int((time.perf_counter() - start) * 1000),
            }
        )
    except (nats_errors.Error, OSError) as exc:
        steps.append({"step": "close", "ok": False, "error": str(exc)})

    return steps


def _choose_output_dir() -> Path:
    candidates = [
        Path("logs"),
        Path(".logs"),
        Path("nats_smoke_results"),
        Path.cwd(),
    ]
    for p in candidates:
        try:
            p.mkdir(parents=True, exist_ok=True)
            test = p / ".write_test"
            test.write_text("ok")
            test.unlink(missing_ok=True)
        except OSError:
            continue
        else:
            return p
    return Path.cwd()


def _write_outputs(result: Result) -> tuple[Path, Path]:
    logs_dir = _choose_output_dir()
    ts = time.strftime("%Y%m%d-%H%M%S")
    json_path = logs_dir / f"nats-smoke-{ts}.json"
    log_path = logs_dir / f"nats-smoke-{ts}.log"

    json_path.write_text(json.dumps(asdict(result), ensure_ascii=False, indent=2))

    lines = [
        f"NATS Smoke Test — URL: {result.nats_url}",
        f"Detected: {json.dumps(result.detected, ensure_ascii=False)}",
        f"Overall: {'OK' if result.ok else 'FAIL'}  Duration: {result.duration_ms} ms",
        "Steps:",
    ]
    lines.extend(
        ["  - " + json.dumps(step, ensure_ascii=False) for step in result.steps]
    )
    log_path.write_text("\n".join(lines))
    return json_path, log_path


async def _amain(nats_url_cli: str | None) -> int:
    nats_url, detected = (
        _detect_nats_url()
        if not nats_url_cli
        else (nats_url_cli, {"source": "cli", "url": nats_url_cli})
    )
    t0 = time.perf_counter()
    user = os.environ.get("NATS_USER") or os.environ.get("NATS_USERNAME")
    password = os.environ.get("NATS_PASSWORD") or os.environ.get("NATS_PASS")
    steps = await _smoke(nats_url, user, password)
    ok = all(s.get("ok") for s in steps if s.get("step") in {"connect", "pubsub"})
    res = Result(
        ok=ok,
        nats_url=nats_url,
        detected=detected,
        steps=steps,
        duration_ms=int((time.perf_counter() - t0) * 1000),
    )
    jpath, lpath = _write_outputs(res)
    print(
        json.dumps(
            {"ok": ok, "json": str(jpath), "log": str(lpath)}, ensure_ascii=False
        )
    )
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--nats-url",
        default=None,
        help="Override NATS URL (e.g., nats://localhost:4222)",
    )
    args = ap.parse_args()
    try:
        return asyncio.run(_amain(args.nats_url))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
