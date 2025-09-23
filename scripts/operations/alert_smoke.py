#!/usr/bin/env python3
"""Synthetic alert smoke test using Pushgateway and Prometheus API."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import typing
import urllib.error
import urllib.parse
import urllib.request

if typing.TYPE_CHECKING:
    from http.client import HTTPResponse

DEFAULT_PUSHGATEWAY = os.environ.get("PUSHGATEWAY_URL", "http://localhost:9091")
DEFAULT_PROMETHEUS = os.environ.get("PROMETHEUS_URL", "http://localhost:9090")
VALUE_TOLERANCE = 1e-6


class AlertSmokeError(RuntimeError):
    """Raised when the smoke test fails."""

    @classmethod
    def prometheus_query_failed(cls, payload: dict[str, typing.Any]) -> AlertSmokeError:
        return cls(f"prometheus_query_failed payload={payload}")

    @classmethod
    def metric_missing(cls) -> AlertSmokeError:
        return cls("metric_not_observed_in_prometheus")

    @classmethod
    def unexpected_metric_value(
        cls, expected: float, observed: float
    ) -> AlertSmokeError:
        return cls(f"unexpected_metric_value expected={expected} observed={observed}")


def _http_request(
    url: str, *, data: bytes | None = None, method: str = "GET"
) -> HTTPResponse:
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "text/plain; version=0.0.4")
    return typing.cast("HTTPResponse", urllib.request.urlopen(req, timeout=5.0))


def _push_metric(
    pushgateway: str, metric: str, value: float, *, job: str, instance: str
) -> None:
    payload = f"{metric} {value}\n".encode()
    url = f"{pushgateway.rstrip('/')}/metrics/job/{urllib.parse.quote(job)}/instance/{urllib.parse.quote(instance)}"
    with _http_request(url, data=payload, method="PUT"):
        return


def _query_prometheus(prometheus: str, expr: str) -> dict[str, typing.Any]:
    query = urllib.parse.quote(expr, safe="")
    url = f"{prometheus.rstrip('/')}/api/v1/query?query={query}"
    with _http_request(url) as resp:
        body = resp.read().decode("utf-8")
    payload = typing.cast(dict[str, typing.Any], json.loads(body))
    if payload.get("status") != "success":  # pragma: no cover - defensive
        raise AlertSmokeError.prometheus_query_failed(payload)
    return payload


def run_smoke(args: argparse.Namespace) -> None:
    job = f"smoke-{int(time.time())}"
    instance = os.uname().nodename
    metric = args.metric

    _push_metric(args.pushgateway_url, metric, args.value, job=job, instance=instance)
    time.sleep(args.wait_seconds)
    payload = _query_prometheus(args.prometheus_url, metric)

    results = payload.get("data", {}).get("result", [])
    if not results:
        raise AlertSmokeError.metric_missing()

    observed_value = float(results[0]["value"][1])
    if abs(observed_value - args.value) > VALUE_TOLERANCE:
        raise AlertSmokeError.unexpected_metric_value(args.value, observed_value)

    # Reset metric to neutral value after verification
    _push_metric(
        args.pushgateway_url, metric, args.reset_value, job=job, instance=instance
    )

    print(
        json.dumps(
            {
                "metric": metric,
                "job": job,
                "instance": instance,
                "observed": observed_value,
                "prometheus": args.prometheus_url,
            }
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Synthetic alert smoke test to validate Pushgateway/Prometheus wiring.",
    )
    parser.add_argument(
        "--pushgateway-url",
        default=DEFAULT_PUSHGATEWAY,
        help="Pushgateway base URL (default: %(default)s)",
    )
    parser.add_argument(
        "--prometheus-url",
        default=DEFAULT_PROMETHEUS,
        help="Prometheus base URL (default: %(default)s)",
    )
    parser.add_argument(
        "--metric",
        default="md_runbook_exit_code",
        help="Metric name to round-trip",
    )
    parser.add_argument(
        "--value",
        type=float,
        default=9.0,
        help="Synthetic value to push during the test",
    )
    parser.add_argument(
        "--reset-value",
        type=float,
        default=0.0,
        help="Value used to reset the metric after the smoke test",
    )
    parser.add_argument(
        "--wait-seconds",
        type=float,
        default=5.0,
        help="Seconds to wait before querying Prometheus",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        run_smoke(args)
    except AlertSmokeError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except (
        urllib.error.HTTPError,
        urllib.error.URLError,
        json.JSONDecodeError,
        TimeoutError,
        OSError,
    ) as exc:
        print(f"unexpected_error: {exc}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
