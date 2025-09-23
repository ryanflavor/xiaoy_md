"""Application configuration module."""

from __future__ import annotations

import os
from pathlib import Path
import typing
from typing import Any, ClassVar

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

_MASK_SHORT_LENGTH = 4
_MASK_LONG_THRESHOLD = 8
_MASK_MIN_PREFIX = 2
_MASK_SUFFIX_LENGTH = 2


def _as_secret(value: SecretStr | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, SecretStr):
        return value.get_secret_value()
    return str(value)


def _mask_secret(value: str | None) -> str | None:
    if value is None or not value:
        return value
    if len(value) <= _MASK_SHORT_LENGTH:
        return "***"
    prefix_len = (
        _MASK_SHORT_LENGTH
        if len(value) > _MASK_LONG_THRESHOLD
        else max(_MASK_MIN_PREFIX, len(value) // 2)
    )
    return f"{value[:prefix_len]}...{value[-_MASK_SUFFIX_LENGTH:]}"


def _has_value(value: SecretStr | str | None) -> bool:
    raw = _as_secret(value)
    return bool(raw and raw.strip())


class BaseCredentialProfile(BaseModel):
    """Shared structure for CTP credential profiles."""

    broker_id: str | None = Field(default=None, description="Broker identifier")
    user_id: str | None = Field(default=None, description="User identifier")
    password: SecretStr | None = Field(default=None, description="Account password")
    md_address: str | None = Field(default=None, description="Market data endpoint")
    td_address: str | None = Field(default=None, description="Trading endpoint")
    app_id: str | None = Field(default=None, description="Application identifier")
    auth_code: SecretStr | None = Field(default=None, description="Authentication code")

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    def has_any(self) -> bool:
        """Return True when any credential field is populated."""
        return any(_has_value(getattr(self, name)) for name in self.model_fields)

    def provided_env_keys(self, mapping: dict[str, str]) -> list[str]:
        """Return provided environment key names for the profile."""
        keys: list[str] = []
        for attr, env_name in mapping.items():
            if _has_value(getattr(self, attr)):
                keys.append(env_name)
        return keys

    def missing_env_keys(self, mapping: dict[str, str]) -> list[str]:
        """Return missing environment key names for the profile."""
        missing: list[str] = []
        for attr, env_name in mapping.items():
            if not _has_value(getattr(self, attr)):
                missing.append(env_name)
        return missing

    def to_safe_dict(self, *, prefix: str | None = None) -> dict[str, Any]:
        """Return masked representation safe for logging/export."""
        safe: dict[str, Any] = {}
        for attr in ("broker_id", "user_id", "md_address", "td_address", "app_id"):
            value = getattr(self, attr)
            key = f"{prefix}_{attr}" if prefix else attr
            safe[key] = value

        for attr in ("password", "auth_code"):
            value = _as_secret(getattr(self, attr))
            key = f"{prefix}_{attr}" if prefix else attr
            safe[key] = _mask_secret(value) if value else value
        return safe


class RouteSelectorError(ValueError):
    """Raised when an invalid credential route selector is provided."""

    def __init__(self, allowed: set[str], provided: str) -> None:
        """Record allowed values and provided selector for error reporting."""
        self.allowed = allowed
        self.provided = provided
        message = (
            "invalid_route_selector "
            f"allowed={sorted(allowed)} provided={provided.lower()}"
        )
        super().__init__(message)


class IncompleteBackupProfileError(ValueError):
    """Raised when backup credential data is partially provided."""

    def __init__(self, missing_fields: list[str]) -> None:
        """Capture missing field names for downstream handling."""
        self.missing_fields = missing_fields
        message = "incomplete_backup_profile missing=" + ",".join(missing_fields)
        super().__init__(message)


class PrimaryCredentialProfile(BaseCredentialProfile):
    """Credential profile populated from primary account env vars."""

    broker_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("CTP_PRIMARY_BROKER_ID", "CTP_BROKER_ID"),
    )
    user_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("CTP_PRIMARY_USER_ID", "CTP_USER_ID"),
    )
    password: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("CTP_PRIMARY_PASSWORD", "CTP_PASSWORD"),
    )
    md_address: str | None = Field(
        default=None,
        validation_alias=AliasChoices("CTP_PRIMARY_MD_ADDRESS", "CTP_MD_ADDRESS"),
    )
    td_address: str | None = Field(
        default=None,
        validation_alias=AliasChoices("CTP_PRIMARY_TD_ADDRESS", "CTP_TD_ADDRESS"),
    )
    app_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("CTP_PRIMARY_APP_ID", "CTP_APP_ID"),
    )
    auth_code: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("CTP_PRIMARY_AUTH_CODE", "CTP_AUTH_CODE"),
    )


class BackupCredentialProfile(BaseCredentialProfile):
    """Credential profile populated from backup account env vars."""

    broker_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("CTP_BACKUP_BROKER_ID"),
    )
    user_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("CTP_BACKUP_USER_ID"),
    )
    password: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("CTP_BACKUP_PASSWORD"),
    )
    md_address: str | None = Field(
        default=None,
        validation_alias=AliasChoices("CTP_BACKUP_MD_ADDRESS"),
    )
    td_address: str | None = Field(
        default=None,
        validation_alias=AliasChoices("CTP_BACKUP_TD_ADDRESS"),
    )
    app_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("CTP_BACKUP_APP_ID"),
    )
    auth_code: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("CTP_BACKUP_AUTH_CODE"),
    )


class AppSettings(BaseSettings):
    """Application settings with environment variable support."""

    _use_env_file = "PYTEST_CURRENT_TEST" not in os.environ
    model_config = SettingsConfigDict(
        env_file=(".env" if _use_env_file else None),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    _SENSITIVE_FIELDS: ClassVar[tuple[str, ...]] = (
        "nats_url",
        "nats_cluster_id",
        "nats_client_id",
        "nats_password",  # pragma: allowlist secret
    )
    _PRIMARY_ENV_MAP: ClassVar[dict[str, str]] = {
        "broker_id": "CTP_PRIMARY_BROKER_ID",
        "user_id": "CTP_PRIMARY_USER_ID",
        "password": "CTP_PRIMARY_PASSWORD",  # pragma: allowlist secret
        "md_address": "CTP_PRIMARY_MD_ADDRESS",
        "td_address": "CTP_PRIMARY_TD_ADDRESS",
        "app_id": "CTP_PRIMARY_APP_ID",
        "auth_code": "CTP_PRIMARY_AUTH_CODE",
    }
    _BACKUP_ENV_MAP: ClassVar[dict[str, str]] = {
        "broker_id": "CTP_BACKUP_BROKER_ID",
        "user_id": "CTP_BACKUP_USER_ID",
        "password": "CTP_BACKUP_PASSWORD",  # pragma: allowlist secret
        "md_address": "CTP_BACKUP_MD_ADDRESS",
        "td_address": "CTP_BACKUP_TD_ADDRESS",
        "app_id": "CTP_BACKUP_APP_ID",
        "auth_code": "CTP_BACKUP_AUTH_CODE",
    }

    @classmethod
    def _transform_external_data(cls, data: dict[str, Any]) -> dict[str, Any]:
        transformed: dict[str, Any] = dict(data)

        primary_payload: dict[str, Any] = {}
        for attr, env_key in cls._PRIMARY_ENV_MAP.items():
            keys_to_check = (env_key, env_key.replace("CTP_PRIMARY_", "CTP_"))
            for key in keys_to_check:
                if key in transformed:
                    primary_payload[attr] = transformed.pop(key)
                    break
        if primary_payload:
            transformed["ctp_primary"] = primary_payload

        backup_payload: dict[str, Any] = {}
        for attr, env_key in cls._BACKUP_ENV_MAP.items():
            if env_key in transformed:
                backup_payload[attr] = transformed.pop(env_key)
        if backup_payload:
            transformed["ctp_backup"] = backup_payload

        return transformed

    @model_validator(mode="before")
    @classmethod
    def _pre_model_validate(cls, data: Any) -> Any:
        if isinstance(data, dict):
            return cls._transform_external_data(dict(data))
        return data

    # Application settings
    app_name: str = Field(default="market-data-service", description="Application name")
    app_version: str = Field(default="0.1.0", description="Application version")
    debug: bool = Field(default=False, description="Debug mode flag")
    environment: str = Field(default="development", description="Environment name")

    # Server settings
    host: str = Field(
        default="127.0.0.1", description="Server host"
    )  # nosec B104 - configurable via env
    port: int = Field(default=8000, description="Server port")

    # NATS settings
    nats_url: str = Field(
        default="nats://localhost:4222",
        description="NATS server URL",
        validation_alias=AliasChoices("NATS_URL"),
    )
    nats_cluster_id: str = Field(
        default="market-data-cluster",
        description="NATS cluster ID",
        validation_alias=AliasChoices("NATS_CLUSTER_ID"),
    )
    nats_client_id: str = Field(
        default="market-data-service",
        description="NATS client ID",
        validation_alias=AliasChoices("NATS_CLIENT_ID"),
    )
    nats_user: str | None = Field(
        default=None,
        description="NATS username for authentication",
        validation_alias=AliasChoices("NATS_USER"),
    )
    nats_password: SecretStr | None = Field(
        default=None,
        description="NATS password for authentication",
        validation_alias=AliasChoices("NATS_PASSWORD"),
    )
    nats_health_check_subject: str = Field(
        default="health.check",
        description="NATS health check subject",
        validation_alias=AliasChoices("NATS_HEALTH_CHECK_SUBJECT"),
    )

    # Logging settings
    log_level: str = Field(default="INFO", description="Logging level")
    log_format: str = Field(default="json", description="Log format (json or text)")

    # Credential governance profiles
    ctp_primary: PrimaryCredentialProfile = Field(
        default_factory=PrimaryCredentialProfile,
        description="Structured primary credential profile",
    )
    ctp_backup: BackupCredentialProfile = Field(
        default_factory=BackupCredentialProfile,
        description="Structured backup credential profile",
    )

    # Routing controls
    ctp_route_selector: str = Field(
        default="auto",
        description="Route selector for credential profile (primary|backup|auto)",
        validation_alias=AliasChoices(
            "CTP_ROUTE_SELECTOR",
            "ACTIVE_FEED",
            "SESSION_CONFIG",
        ),
    )

    # Serialization strategy for publisher payloads
    serialization_strategy: str = Field(
        default="json", description="Serialization strategy for payloads (json|pickle)"
    )

    # Rate limiting configuration for control plane subscribe operations
    subscribe_rate_limit_window_seconds: float = Field(
        default=60.0,
        description="Sliding window in seconds for subscribe rate limiting",
        validation_alias=AliasChoices("SUBSCRIBE_RATE_LIMIT_WINDOW_SECONDS"),
    )
    subscribe_rate_limit_max_requests: int = Field(
        default=50,
        description="Maximum subscribe operations allowed per rate limit window",
        validation_alias=AliasChoices("SUBSCRIBE_RATE_LIMIT_MAX_REQUESTS"),
    )
    rate_limit_login_per_minute: int = Field(
        default=5,
        description="Maximum login attempts per minute",
        validation_alias=AliasChoices("RATE_LIMIT_LOGIN_PER_MINUTE"),
        ge=1,
    )
    rate_limit_subscribe_per_second: int = Field(
        default=10,
        description="Maximum subscribe operations per second",
        validation_alias=AliasChoices("RATE_LIMIT_SUBSCRIBE_PER_SECOND"),
        ge=1,
    )

    tick_queue_maxsize: int = Field(
        default=50000,
        description="Maximum number of ticks buffered before dropping",
        ge=1,
    )

    enable_ingest_metrics: bool = Field(
        default=True,
        description="Enable ingest metrics exporter",
        validation_alias=AliasChoices("ENABLE_INGEST_METRICS"),
    )
    ingest_metrics_host: str = Field(
        default="0.0.0.0",  # nosec B104 - metrics exporter intentionally binds
        description="Bind host for ingest metrics exporter",
        validation_alias=AliasChoices("INGEST_METRICS_HOST", "METRICS_BIND_HOST"),
    )
    ingest_metrics_port: int = Field(
        default=9100,
        description="Bind port for ingest metrics exporter",
        validation_alias=AliasChoices(
            "INGEST_METRICS_PORT", "INGEST_METRICS_BIND_PORT"
        ),
        ge=1,
        le=65535,
    )
    metrics_feed_label: str | None = Field(
        default=None,
        description="Override feed label applied to ingest metrics",
        validation_alias=AliasChoices("METRICS_FEED_LABEL"),
    )
    metrics_account_label: str | None = Field(
        default=None,
        description="Override account label applied to ingest metrics",
        validation_alias=AliasChoices("METRICS_ACCOUNT_LABEL"),
    )
    subscription_metrics_host: str = Field(
        default="0.0.0.0",  # nosec B104 - metrics exporter intentionally binds
        description="Bind host for subscription worker metrics exporter",
        validation_alias=AliasChoices("SUBSCRIPTION_METRICS_HOST"),
    )
    subscription_metrics_port: int = Field(
        default=9101,
        description="Bind port for subscription worker metrics exporter",
        validation_alias=AliasChoices("SUBSCRIPTION_METRICS_PORT"),
        ge=1,
        le=65535,
    )
    pushgateway_url: str = Field(
        default="http://localhost:9091",
        description="Prometheus Pushgateway endpoint",
        validation_alias=AliasChoices("PUSHGATEWAY_URL"),
    )
    ops_api_tokens: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Bearer tokens authorized to call the operations API",
        validation_alias=AliasChoices("OPS_API_TOKENS", "OPS_API_TOKEN"),
    )
    ops_runbook_script: Path = Field(
        default=Path("scripts/operations/start_live_env.sh"),
        description="Path to the runbook orchestration script",
    )
    ops_health_output_dir: Path = Field(
        default=Path("logs/runbooks"),
        description="Directory for health-check artifacts and logs",
    )
    ops_status_file: Path = Field(
        default=Path("logs/runbooks/ops_console_status.json"),
        description="Status cache file for operations console API",
    )
    ops_prometheus_base_url: str | None = Field(
        default=None,
        description="Base URL for Prometheus HTTP API consumption",
        validation_alias=AliasChoices("OPS_PROMETHEUS_URL", "PROMETHEUS_BASE_URL"),
    )
    ops_prometheus_timeout_seconds: float = Field(
        default=3.0,
        description="Timeout (seconds) for Prometheus queries",
        ge=0.5,
        le=30.0,
    )

    # Legacy single-profile aliases for compatibility (non-default route)
    legacy_ctp_broker_id: str | None = Field(
        default=None,
        alias="ctp_broker_id",
        description="Legacy broker id",
        validation_alias=AliasChoices("CTP_BROKER_ID"),
    )
    legacy_ctp_user_id: str | None = Field(
        default=None,
        alias="ctp_user_id",
        description="Legacy user id",
        validation_alias=AliasChoices("CTP_USER_ID"),
    )
    legacy_ctp_password: SecretStr | None = Field(
        default=None,
        alias="ctp_password",
        description="Legacy password",
        validation_alias=AliasChoices("CTP_PASSWORD"),
    )
    legacy_ctp_md_address: str | None = Field(
        default=None,
        alias="ctp_md_address",
        description="Legacy market data address",
        validation_alias=AliasChoices("CTP_MD_ADDRESS"),
    )
    legacy_ctp_td_address: str | None = Field(
        default=None,
        alias="ctp_td_address",
        description="Legacy trading address",
        validation_alias=AliasChoices("CTP_TD_ADDRESS"),
    )
    legacy_ctp_app_id: str | None = Field(
        default=None,
        alias="ctp_app_id",
        description="Legacy app id",
        validation_alias=AliasChoices("CTP_APP_ID"),
    )
    legacy_ctp_auth_code: SecretStr | None = Field(
        default=None,
        alias="ctp_auth_code",
        description="Legacy auth code",
        validation_alias=AliasChoices("CTP_AUTH_CODE"),
    )

    @property
    def is_production(self) -> bool:
        """Check if running in production environment."""
        return self.environment.lower() == "production"

    @property
    def is_development(self) -> bool:
        """Check if running in development environment."""
        return self.environment.lower() == "development"

    @model_validator(mode="after")
    def _validate_backup_profile(self) -> AppSettings:
        self.ctp_route_selector = self._normalize_route_selector(
            self.ctp_route_selector
        )
        provided = [
            env_name
            for attr, env_name in self._BACKUP_ENV_MAP.items()
            if _has_value(getattr(self.ctp_backup, attr))
        ]
        if provided and len(provided) != len(self._BACKUP_ENV_MAP):
            missing = [
                env_name
                for attr, env_name in self._BACKUP_ENV_MAP.items()
                if not _has_value(getattr(self.ctp_backup, attr))
            ]
            raise IncompleteBackupProfileError(missing)
        self._normalize_ops_tokens()
        self._normalize_ops_paths()
        return self

    @staticmethod
    def _normalize_route_selector(value: str) -> str:
        allowed = {"primary", "backup", "auto"}
        normalized = value.lower()
        if normalized not in allowed:
            raise RouteSelectorError(allowed, value)
        return normalized

    def _normalize_ops_tokens(self) -> None:
        raw_values = list(self.ops_api_tokens)
        if (
            raw_values
            and len(raw_values) > 1
            and all(len(str(item)) == 1 for item in raw_values)
        ):
            raw_values = ["".join(str(item) for item in raw_values)]
        tokens: list[str] = []
        for value in raw_values:
            for part in str(value).replace("\n", ",").split(","):
                token = part.strip()
                if token and token not in tokens:
                    tokens.append(token)
        self.ops_api_tokens = tuple(tokens)

    def _normalize_ops_paths(self) -> None:
        self.ops_runbook_script = Path(self.ops_runbook_script).expanduser().resolve()
        self.ops_health_output_dir = (
            Path(self.ops_health_output_dir).expanduser().resolve()
        )
        self.ops_status_file = Path(self.ops_status_file).expanduser().resolve()

    def missing_primary_fields(self) -> list[str]:
        """Return missing primary credential fields for live orchestration."""
        return [
            env_name
            for attr, env_name in self._PRIMARY_ENV_MAP.items()
            if not _has_value(getattr(self.ctp_primary, attr))
        ]

    def missing_backup_fields(self) -> list[str]:
        """Return missing backup credential fields when any backup data exists."""
        provided = [
            env_name
            for attr, env_name in self._BACKUP_ENV_MAP.items()
            if _has_value(getattr(self.ctp_backup, attr))
        ]
        if not provided:
            return []
        return [
            env_name
            for attr, env_name in self._BACKUP_ENV_MAP.items()
            if not _has_value(getattr(self.ctp_backup, attr))
        ]

    def has_backup_profile(self) -> bool:
        """Return True when backup credentials are fully defined."""
        return all(
            _has_value(getattr(self.ctp_backup, attr)) for attr in self._BACKUP_ENV_MAP
        )

    def invalid_endpoint_fields(self) -> list[str]:
        """Return endpoint fields that do not match tcp:// prefix."""
        endpoints = {
            "CTP_PRIMARY_MD_ADDRESS": self.ctp_primary.md_address,
            "CTP_PRIMARY_TD_ADDRESS": self.ctp_primary.td_address,
            "CTP_BACKUP_MD_ADDRESS": self.ctp_backup.md_address,
            "CTP_BACKUP_TD_ADDRESS": self.ctp_backup.td_address,
        }
        invalid = []
        for name, value in endpoints.items():
            raw = _as_secret(value)
            if raw and not raw.startswith("tcp://"):
                invalid.append(name)
        return invalid

    def resolved_metrics_feed(self) -> str:
        """Return lowercase feed label used for ingest metrics."""
        candidate = self.metrics_feed_label or self.ctp_route_selector
        if not candidate:
            return "primary"
        return candidate.lower()

    def resolved_metrics_account(self) -> str:
        """Return masked account identifier for ingest metrics labels."""
        if self.metrics_account_label:
            return self.metrics_account_label

        primary_user = _as_secret(self.ctp_primary.user_id)
        if primary_user:
            return _mask_secret(primary_user) or "unknown"

        active_user = self.ctp_user_id
        if active_user:
            masked_active = _mask_secret(active_user)
            return masked_active or "unknown"

        backup_user = _as_secret(self.ctp_backup.user_id)
        if backup_user:
            return _mask_secret(backup_user) or "unknown"

        return "unknown"

    def _resolve_profile_field(self, field_suffix: str) -> SecretStr | str | None:
        """Resolve a field from active credential profile."""
        primary_value = typing.cast(
            SecretStr | str | None, getattr(self.ctp_primary, field_suffix)
        )
        backup_value = typing.cast(
            SecretStr | str | None, getattr(self.ctp_backup, field_suffix)
        )

        if self.ctp_route_selector == "backup" and _has_value(backup_value):
            return backup_value
        if self.ctp_route_selector == "primary":
            return primary_value
        # auto mode prefers primary but falls back to backup when primary missing
        if _has_value(primary_value):
            return primary_value
        if _has_value(backup_value):
            return backup_value
        legacy_attr = f"legacy_ctp_{field_suffix}"
        if hasattr(self, legacy_attr):
            legacy_value = typing.cast(
                SecretStr | str | None, getattr(self, legacy_attr)
            )
            if _has_value(legacy_value):
                return legacy_value
        return primary_value

    @property
    def ctp_primary_broker_id(self) -> str | None:
        return self.ctp_primary.broker_id

    @property
    def ctp_primary_user_id(self) -> str | None:
        return self.ctp_primary.user_id

    @property
    def ctp_primary_password(self) -> SecretStr | None:
        return self.ctp_primary.password

    @property
    def ctp_primary_md_address(self) -> str | None:
        return self.ctp_primary.md_address

    @property
    def ctp_primary_td_address(self) -> str | None:
        return self.ctp_primary.td_address

    @property
    def ctp_primary_app_id(self) -> str | None:
        return self.ctp_primary.app_id

    @property
    def ctp_primary_auth_code(self) -> SecretStr | None:
        return self.ctp_primary.auth_code

    @property
    def ctp_backup_broker_id(self) -> str | None:
        return self.ctp_backup.broker_id

    @property
    def ctp_backup_user_id(self) -> str | None:
        return self.ctp_backup.user_id

    @property
    def ctp_backup_password(self) -> SecretStr | None:
        return self.ctp_backup.password

    @property
    def ctp_backup_md_address(self) -> str | None:
        return self.ctp_backup.md_address

    @property
    def ctp_backup_td_address(self) -> str | None:
        return self.ctp_backup.td_address

    @property
    def ctp_backup_app_id(self) -> str | None:
        return self.ctp_backup.app_id

    @property
    def ctp_backup_auth_code(self) -> SecretStr | None:
        return self.ctp_backup.auth_code

    @property
    def ctp_broker_id(self) -> str | None:
        """Return broker id for active profile."""
        value = self._resolve_profile_field("broker_id")
        return _as_secret(value) if isinstance(value, SecretStr) else value

    @property
    def ctp_user_id(self) -> str | None:
        value = self._resolve_profile_field("user_id")
        return _as_secret(value) if isinstance(value, SecretStr) else value

    @property
    def ctp_password(self) -> str | None:
        return _as_secret(self._resolve_profile_field("password"))

    @property
    def ctp_md_address(self) -> str | None:
        value = self._resolve_profile_field("md_address")
        return _as_secret(value) if isinstance(value, SecretStr) else value

    @property
    def ctp_td_address(self) -> str | None:
        value = self._resolve_profile_field("td_address")
        return _as_secret(value) if isinstance(value, SecretStr) else value

    @property
    def ctp_app_id(self) -> str | None:
        value = self._resolve_profile_field("app_id")
        return _as_secret(value) if isinstance(value, SecretStr) else value

    @property
    def ctp_auth_code(self) -> str | None:
        return _as_secret(self._resolve_profile_field("auth_code"))

    def to_dict(self) -> dict[str, Any]:
        """Convert settings to dictionary."""
        return self.model_dump()

    def to_dict_safe(self) -> dict[str, Any]:
        """Convert settings to dictionary with sensitive fields masked."""
        data = self.model_dump(mode="python")
        for field in self._SENSITIVE_FIELDS:
            raw_value = _as_secret(getattr(self, field))
            if raw_value:
                data[field] = _mask_secret(raw_value)

        primary_safe = {
            "broker_id": self.ctp_primary.broker_id,
            "user_id": self.ctp_primary.user_id,
            "password": _mask_secret(_as_secret(self.ctp_primary.password)),
            "md_address": self.ctp_primary.md_address,
            "td_address": self.ctp_primary.td_address,
            "app_id": self.ctp_primary.app_id,
            "auth_code": _mask_secret(_as_secret(self.ctp_primary.auth_code)),
        }
        backup_safe = {
            "broker_id": self.ctp_backup.broker_id,
            "user_id": self.ctp_backup.user_id,
            "password": _mask_secret(_as_secret(self.ctp_backup.password)),
            "md_address": self.ctp_backup.md_address,
            "td_address": self.ctp_backup.td_address,
            "app_id": self.ctp_backup.app_id,
            "auth_code": _mask_secret(_as_secret(self.ctp_backup.auth_code)),
        }

        data["ctp_primary"] = primary_safe
        data["ctp_backup"] = backup_safe

        for key, value in primary_safe.items():
            data[f"ctp_primary_{key}"] = value
        for key, value in backup_safe.items():
            data[f"ctp_backup_{key}"] = value

        data["ctp_password"] = _mask_secret(
            _as_secret(self._resolve_profile_field("password"))
        )
        data["ctp_auth_code"] = _mask_secret(
            _as_secret(self._resolve_profile_field("auth_code"))
        )

        return data


# Global settings instance
settings = AppSettings()


def get_settings() -> AppSettings:
    """Get application settings."""
    return settings
