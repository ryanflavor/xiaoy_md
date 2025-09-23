#!/usr/bin/env python3
"""Diagnose live CTP connector independently of the ingest entry.

Loads CTP_* from an .env file, builds the vn.py setting (中文键),
runs live_gateway_connect for a short window, and prints any exception stack.

Usage:
  uv run python scripts/diag_live_connector.py --env-file .env --duration 8
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import threading
import time
import traceback


def _mask(val: str | None) -> str:
    if not val:
        return ""
    if len(val) <= 4:  # noqa: PLR2004 - small values fully masked
        return "***"
    return f"{val[:2]}***{val[-2:]}"


def _load_env(env_file: Path, force: bool) -> None:
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        t = line.strip()
        if not t or t.startswith("#") or "=" not in t:
            continue
        k, v = t.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if (
            k.startswith("CTP_") or k in {"NATS_URL", "NATS_USER", "NATS_PASSWORD"}
        ) and (force or not os.getenv(k)):
            os.environ[k] = v


def _norm(addr: str | None) -> str:
    if not addr:
        return ""
    return addr if addr.startswith(("tcp://", "ssl://")) else f"tcp://{addr}"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Diagnose live connector")
    p.add_argument("--env-file", default=".env", help="Path to .env file")
    p.add_argument("--duration", type=float, default=8.0, help="Run seconds")
    p.add_argument(
        "--force-env",
        action="store_true",
        help="Force override environment with .env values",
    )
    args = p.parse_args(argv)

    _load_env(Path(args.env_file), force=args.force_env)

    setting: dict[str, object] = {
        "用户名": os.getenv("CTP_USER_ID") or "",
        "密码": os.getenv("CTP_PASSWORD") or "",
        "经纪商代码": os.getenv("CTP_BROKER_ID") or "",
        "交易服务器": _norm(os.getenv("CTP_TD_ADDRESS")),
        "行情服务器": _norm(os.getenv("CTP_MD_ADDRESS")),
        "产品名称": os.getenv("CTP_APP_ID") or "",
        "授权编码": os.getenv("CTP_AUTH_CODE") or "",
    }

    print("=== DIAG: connector setting (masked) ===")
    masked: dict[str, str] = {}
    for k, v in setting.items():
        sv = v if isinstance(v, str) else str(v)
        masked[k] = _mask(sv) if k not in ("交易服务器", "行情服务器") else sv

    print(masked)

    from src.infrastructure.ctp_live_connector import live_gateway_connect

    stop = {"flag": False}

    def should_shutdown() -> bool:
        return stop["flag"]

    def run_connector() -> None:
        try:
            live_gateway_connect(setting, should_shutdown)
        except RuntimeError:
            print("=== CONNECTOR EXCEPTION (RuntimeError) ===")
            traceback.print_exc()
        except Exception as e:  # noqa: BLE001 - diagnostic catch-all to surface stack
            # Log the type and message without hiding the stack
            print(f"=== CONNECTOR EXCEPTION: {type(e).__name__}: {e} ===")
            traceback.print_exc()

    t = threading.Thread(target=run_connector, daemon=True)
    t.start()
    time.sleep(max(0.1, float(args.duration)))
    stop["flag"] = True
    t.join(timeout=5)
    print("=== DIAG: done ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
