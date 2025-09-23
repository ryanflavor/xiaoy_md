"""Environment validation CLI for live orchestration profiles."""

from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
import sys
import typing
from typing import TYPE_CHECKING

from pydantic import ValidationError

from src.config import AppSettings

if TYPE_CHECKING:
    from collections.abc import Iterable

LOGGER = logging.getLogger("operations.validate_env")

PRIMARY_KEYS = [
    "CTP_PRIMARY_BROKER_ID",
    "CTP_PRIMARY_USER_ID",
    "CTP_PRIMARY_PASSWORD",
    "CTP_PRIMARY_MD_ADDRESS",
    "CTP_PRIMARY_TD_ADDRESS",
    "CTP_PRIMARY_APP_ID",
    "CTP_PRIMARY_AUTH_CODE",
]

BACKUP_KEYS = [
    "CTP_BACKUP_BROKER_ID",
    "CTP_BACKUP_USER_ID",
    "CTP_BACKUP_PASSWORD",
    "CTP_BACKUP_MD_ADDRESS",
    "CTP_BACKUP_TD_ADDRESS",
    "CTP_BACKUP_APP_ID",
    "CTP_BACKUP_AUTH_CODE",
]

ALIAS_FALLBACKS = {
    "CTP_PRIMARY_BROKER_ID": "CTP_BROKER_ID",
    "CTP_PRIMARY_USER_ID": "CTP_USER_ID",
    "CTP_PRIMARY_PASSWORD": "CTP_PASSWORD",  # pragma: allowlist secret
    "CTP_PRIMARY_MD_ADDRESS": "CTP_MD_ADDRESS",
    "CTP_PRIMARY_TD_ADDRESS": "CTP_TD_ADDRESS",
    "CTP_PRIMARY_APP_ID": "CTP_APP_ID",
    "CTP_PRIMARY_AUTH_CODE": "CTP_AUTH_CODE",  # pragma: allowlist secret
}


class EnvironmentFileMissingError(FileNotFoundError):
    """Raised when an environment configuration file is not present."""

    def __init__(self, path: Path) -> None:
        """Store missing path and provide structured error message."""
        self.path = path
        super().__init__(f"environment_file_missing path={path}")


def _configure_logging() -> None:
    """Configure JSON logger for stdout output."""
    if LOGGER.handlers:
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.INFO)


def _emit(level: int, message: str, **extra: object) -> None:
    """Emit JSON log payload."""
    payload = {"event": message, **extra}
    LOGGER.log(level, json.dumps(payload, ensure_ascii=False))


def _parse_env_file(path: Path) -> dict[str, str]:
    """Parse key=value pairs from an env file."""
    values: dict[str, str] = {}
    if not path.exists():
        raise EnvironmentFileMissingError(path)

    with path.open(encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export ") :]
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            values[key] = value
    return values


def _normalize_env(env_mapping: dict[str, str]) -> dict[str, str]:
    """Normalize environment keys to uppercase strings for settings."""
    return {str(key).strip(): str(value) for key, value in env_mapping.items() if key}


def _get_env_value(env: dict[str, str], key: str) -> str:
    """Resolve environment value with optional fallback alias."""
    value = env.get(key, "").strip()
    if value:
        return value
    fallback = ALIAS_FALLBACKS.get(key)
    if fallback:
        return env.get(fallback, "").strip()
    return ""


def _format_validation_errors(errors: Iterable[dict[str, object]]) -> list[str]:
    """Format pydantic validation errors for human output."""
    formatted: list[str] = []
    for error in errors:
        location = error.get("loc", ())
        if isinstance(location, tuple):
            loc_str = "_".join(str(part).upper() for part in location)
        else:
            loc_str = str(location).upper()
        formatted.append(f"{loc_str}: {error.get('msg', 'invalid configuration')}")
    return formatted


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Validate live environment credential and rate-limit profiles.",
    )
    parser.add_argument(
        "--source",
        type=Path,
        help="Path to environment file to validate",
    )
    parser.add_argument(
        "--profile",
        default="live",
        help="Operator profile label for logging context",
    )
    parser.add_argument(
        "--require-backup",
        action="store_true",
        help="Fail when backup credential profile is missing",
    )
    return parser.parse_args(argv)


def _collect_env(args: argparse.Namespace) -> dict[str, str]:
    """Merge OS environment with optional file overrides."""
    env_data: dict[str, str] = _normalize_env(os.environ.copy())
    if args.source:
        file_env = _normalize_env(_parse_env_file(args.source))
        env_data.update(file_env)
    return env_data


def _build_summary(settings: AppSettings, backup_detected: bool) -> dict[str, object]:
    """Return masked summary for logging."""
    safe = settings.to_dict_safe()
    keys = [
        "ctp_route_selector",
        "ctp_primary_broker_id",
        "ctp_backup_broker_id",
        "subscribe_rate_limit_window_seconds",
        "subscribe_rate_limit_max_requests",
        "rate_limit_login_per_minute",
        "rate_limit_subscribe_per_second",
        "enable_ingest_metrics",
        "ingest_metrics_host",
        "ingest_metrics_port",
        "metrics_feed_label",
        "metrics_account_label",
        "subscription_metrics_host",
        "subscription_metrics_port",
    ]
    summary = {key: safe.get(key) for key in keys if key in safe}
    summary["backup_profile_detected"] = backup_detected
    return summary


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    args = parse_args(argv)
    _configure_logging()

    try:
        env_data = _collect_env(args)
        primary_missing_from_input = [
            key for key in PRIMARY_KEYS if not _get_env_value(env_data, key)
        ]
        backup_values_input = {
            key: _get_env_value(env_data, key) for key in BACKUP_KEYS
        }
        backup_provided_input = [
            key for key, value in backup_values_input.items() if value
        ]
        backup_missing_from_input = []
        if backup_provided_input and len(backup_provided_input) != len(BACKUP_KEYS):
            backup_missing_from_input = [
                key for key, value in backup_values_input.items() if not value
            ]

        settings = AppSettings.model_validate(env_data, context={"_env_file": None})
    except EnvironmentFileMissingError as exc:
        _emit(
            logging.ERROR,
            "environment_validation_failed",
            profile=args.profile,
            error=str(exc),
        )
        sys.stderr.write(f"{exc}\n")
        return 1
    except ValidationError as exc:
        errors = _format_validation_errors(
            typing.cast("Iterable[dict[str, object]]", exc.errors())
        )
        _emit(
            logging.ERROR,
            "environment_validation_failed",
            profile=args.profile,
            errors=errors,
        )
        sys.stderr.write("\n".join(errors) + "\n")
        return 1
    except ValueError as exc:
        # Raised by AppSettings when backup profile incomplete
        message = str(exc)
        _emit(
            logging.ERROR,
            "environment_validation_failed",
            profile=args.profile,
            errors=[message],
        )
        sys.stderr.write(f"{message}\n")
        return 1

    missing_primary = settings.missing_primary_fields()
    missing_backup = settings.missing_backup_fields()
    invalid_endpoints = settings.invalid_endpoint_fields()
    issues: list[str] = []

    combined_primary_missing = sorted(
        set(primary_missing_from_input) | set(missing_primary)
    )
    if combined_primary_missing:
        issues.append(
            "Missing required primary credentials: "
            + ", ".join(combined_primary_missing)
        )

    combined_backup_missing = sorted(
        set(backup_missing_from_input) | set(missing_backup)
    )
    if combined_backup_missing:
        issues.append(
            "Incomplete backup credentials: " + ", ".join(combined_backup_missing)
        )

    if invalid_endpoints:
        issues.append(
            "Endpoint(s) must start with tcp://: " + ", ".join(invalid_endpoints)
        )

    backup_detected = settings.has_backup_profile()
    if (
        not backup_detected
        and not backup_missing_from_input
        and len(backup_provided_input) == len(BACKUP_KEYS)
    ):
        backup_detected = True

    if args.require_backup and not backup_detected:
        issues.append("Backup profile required but not provided")

    if issues:
        _emit(
            logging.ERROR,
            "environment_validation_failed",
            profile=args.profile,
            errors=issues,
        )
        sys.stderr.write("\n".join(issues) + "\n")
        return 1

    _emit(
        logging.INFO,
        "environment_validation_passed",
        profile=args.profile,
        summary=_build_summary(settings, backup_detected),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
