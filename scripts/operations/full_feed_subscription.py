#!/usr/bin/env python3
"""CLI entrypoint for the full-feed subscription workflow."""

from __future__ import annotations

from src.operations.full_feed_subscription import main

if __name__ == "__main__":
    raise SystemExit(main())
