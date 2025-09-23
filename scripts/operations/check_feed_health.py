#!/usr/bin/env python3
"""CLI entrypoint for subscription health checks."""

from __future__ import annotations

from src.operations.check_feed_health import main

if __name__ == "__main__":
    raise SystemExit(main())
