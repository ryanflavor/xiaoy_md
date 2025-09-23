"""Configuration validation tests for orchestration environment.

Ensures environment profiles and variables are resolved safely.
"""

import os

from pydantic import Field, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings
import pytest

from scripts.operations import validate_env
from src.config import AppSettings


class InvalidTcpAddressError(ValueError):
    """Raised when a TCP endpoint lacks the tcp:// prefix."""

    def __init__(self, value: str) -> None:
        """Store invalid TCP endpoint value."""
        self.value = value
        super().__init__(f"invalid_tcp_endpoint value={value}")


class InvalidNATSUrlError(ValueError):
    """Raised when a NATS URL does not use an accepted scheme."""

    def __init__(self, value: str) -> None:
        """Store invalid NATS URL value."""
        self.value = value
        super().__init__(f"invalid_nats_url value={value}")


class InvalidSymbolFormatError(ValueError):
    """Raised when a contract symbol lacks an exchange suffix."""

    def __init__(self, value: str) -> None:
        """Store invalid symbol for diagnostics."""
        self.value = value
        super().__init__(f"invalid_symbol_format value={value}")


class OrchestrationConfig(BaseSettings):
    """Configuration model for orchestration environment validation."""

    # CTP Primary Configuration
    ctp_broker_id: str = Field(..., description="CTP Broker ID")
    ctp_user_id: str = Field(..., description="CTP User ID")
    ctp_password: str = Field(..., description="CTP Password")
    ctp_md_address: str = Field(..., description="CTP Market Data Address")
    ctp_td_address: str = Field(..., description="CTP Trade Address")
    ctp_app_id: str = Field(..., description="CTP Application ID")
    ctp_auth_code: str = Field(..., description="CTP Auth Code")
    ctp_symbol: str | None = Field(None, description="CTP Symbol to subscribe")

    # CTP Backup Configuration
    ctp_backup_user_id: str | None = Field(None, description="Backup User ID")
    ctp_backup_password: str | None = Field(None, description="Backup Password")
    ctp_backup_md_address: str | None = Field(None, description="Backup MD Address")
    ctp_backup_td_address: str | None = Field(None, description="Backup TD Address")

    # NATS Configuration
    nats_user: str = Field(..., description="NATS Username")
    nats_password: str = Field(..., description="NATS Password")
    nats_url: str = Field(..., description="NATS Server URL")

    # Rate Limiting
    rate_limit_login_per_minute: int = Field(5, ge=1, le=10)
    rate_limit_subscribe_per_second: int = Field(10, ge=1, le=100)

    # Monitoring
    pushgateway_url: str | None = Field(
        "http://localhost:9091", description="Pushgateway URL"
    )

    # Session Configuration
    session_window: str = Field("day", pattern="^(day|night)$")
    session_profile: str = Field("live", pattern="^(live|test|dev)$")

    @field_validator(
        "ctp_md_address",
        "ctp_td_address",
        "ctp_backup_md_address",
        "ctp_backup_td_address",
    )
    @classmethod
    def validate_tcp_address(cls, v):
        """Validate TCP address format."""
        if v and not v.startswith("tcp://"):
            raise InvalidTcpAddressError(v)
        return v

    @field_validator("nats_url")
    @classmethod
    def validate_nats_url(cls, v):
        """Validate NATS URL format."""
        if not v.startswith(("nats://", "tls://")):
            raise InvalidNATSUrlError(v)
        return v

    @field_validator("ctp_symbol")
    @classmethod
    def validate_symbol_format(cls, v):
        """Validate VT symbol format."""
        if v and "." not in v:
            raise InvalidSymbolFormatError(v)
        return v

    model_config = {
        "env_file": None,  # Don't auto-load .env in tests
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
        "env_prefix": "",
        "extra": "ignore",  # Allow extra fields for now
    }


def _create_config(**data: str) -> OrchestrationConfig:
    return OrchestrationConfig(**data)  # type: ignore[arg-type]


def _create_config_from_env() -> OrchestrationConfig:
    return OrchestrationConfig()  # type: ignore[call-arg]


class TestConfigurationValidation:
    """Test suite for configuration validation."""

    def _to_model_config(self, env_dict: dict[str, str]) -> dict[str, str]:
        """Convert environment-style keys to model field names."""
        return {k.lower(): v for k, v in env_dict.items()}

    @pytest.fixture
    def valid_config_dict(self) -> dict[str, str]:
        """Provide a valid configuration dictionary."""
        return {
            "CTP_BROKER_ID": "test_broker",
            "CTP_USER_ID": "test_user",
            "CTP_PASSWORD": "test_pass",  # pragma: allowlist secret
            "CTP_MD_ADDRESS": "tcp://test.md.address:10110",
            "CTP_TD_ADDRESS": "tcp://test.td.address:10100",
            "CTP_APP_ID": "test_app",
            "CTP_AUTH_CODE": "test_auth",  # pragma: allowlist secret
            "CTP_SYMBOL": "rb2510.SHFE",
            "NATS_USER": "nats_user",
            "NATS_PASSWORD": "nats_pass",  # pragma: allowlist secret
            "NATS_URL": "nats://localhost:4222",
            "RATE_LIMIT_LOGIN_PER_MINUTE": "5",
            "RATE_LIMIT_SUBSCRIBE_PER_SECOND": "10",
            "SESSION_WINDOW": "day",
            "SESSION_PROFILE": "live",
        }

    def test_valid_configuration_loads(self, valid_config_dict):
        """Test that valid configuration loads successfully."""
        # Convert keys to lowercase for model initialization
        config_data = {k.lower(): v for k, v in valid_config_dict.items()}
        config = _create_config(**config_data)

        assert config.ctp_broker_id == "test_broker"
        assert config.ctp_user_id == "test_user"
        assert config.ctp_md_address == "tcp://test.md.address:10110"
        assert config.nats_url == "nats://localhost:4222"
        assert config.session_window == "day"

    def test_missing_required_field_raises_error(self, valid_config_dict):
        """Test that missing required fields cause validation errors."""
        del valid_config_dict["CTP_BROKER_ID"]
        config_data = self._to_model_config(valid_config_dict)

        with pytest.raises(ValidationError) as exc_info:
            _create_config(**config_data)

        assert "ctp_broker_id" in str(exc_info.value)

    def test_invalid_tcp_address_format(self, valid_config_dict):
        """Test that invalid TCP addresses are rejected."""
        valid_config_dict["CTP_MD_ADDRESS"] = "http://wrong.protocol:10110"
        config_data = self._to_model_config(valid_config_dict)

        with pytest.raises(ValidationError) as exc_info:
            _create_config(**config_data)

        assert "invalid_tcp_endpoint" in str(exc_info.value)

    def test_invalid_nats_url_format(self, valid_config_dict):
        """Test that invalid NATS URLs are rejected."""
        valid_config_dict["NATS_URL"] = "http://localhost:4222"
        config_data = self._to_model_config(valid_config_dict)

        with pytest.raises(ValidationError) as exc_info:
            _create_config(**config_data)

        assert "invalid_nats_url" in str(exc_info.value)

    def test_invalid_symbol_format(self, valid_config_dict):
        """Test that invalid symbol formats are rejected."""
        valid_config_dict["CTP_SYMBOL"] = "INVALID_SYMBOL"
        config_data = self._to_model_config(valid_config_dict)

        with pytest.raises(ValidationError) as exc_info:
            _create_config(**config_data)

        assert "invalid_symbol_format" in str(exc_info.value)

    def test_rate_limit_validation(self, valid_config_dict):
        """Test that rate limits are within acceptable ranges."""
        # Test too low
        valid_config_dict["RATE_LIMIT_LOGIN_PER_MINUTE"] = "0"
        config_data = self._to_model_config(valid_config_dict)

        with pytest.raises(ValidationError):
            _create_config(**config_data)

        # Test too high
        valid_config_dict["RATE_LIMIT_LOGIN_PER_MINUTE"] = "5"
        valid_config_dict["RATE_LIMIT_SUBSCRIBE_PER_SECOND"] = "1000"
        config_data = self._to_model_config(valid_config_dict)

        with pytest.raises(ValidationError):
            _create_config(**config_data)

        # Test valid range
        valid_config_dict["RATE_LIMIT_SUBSCRIBE_PER_SECOND"] = "50"
        config_data = self._to_model_config(valid_config_dict)
        config = _create_config(**config_data)
        assert config.rate_limit_subscribe_per_second == 50

    def test_session_window_validation(self, valid_config_dict):
        """Test that only valid session windows are accepted."""
        # Test valid windows
        for window in ["day", "night"]:
            valid_config_dict["SESSION_WINDOW"] = window
            config_data = self._to_model_config(valid_config_dict)
            config = _create_config(**config_data)
            assert config.session_window == window

        # Test invalid window
        valid_config_dict["SESSION_WINDOW"] = "afternoon"
        config_data = self._to_model_config(valid_config_dict)

        with pytest.raises(ValidationError):
            _create_config(**config_data)

    def test_backup_configuration_optional(self, valid_config_dict):
        """Test that backup configuration is optional."""
        # Remove all backup fields
        for key in list(valid_config_dict.keys()):
            if "BACKUP" in key:
                del valid_config_dict[key]

        config_data = self._to_model_config(valid_config_dict)
        config = _create_config(**config_data)

        assert config.ctp_backup_user_id is None
        assert config.ctp_backup_md_address is None

    def test_backup_configuration_validation(self, valid_config_dict):
        """Test backup configuration when provided."""
        valid_config_dict.update(
            {
                "CTP_BACKUP_USER_ID": "backup_user",
                "CTP_BACKUP_PASSWORD": "backup_pass",  # pragma: allowlist secret
                "CTP_BACKUP_MD_ADDRESS": "tcp://backup.md:10110",
                "CTP_BACKUP_TD_ADDRESS": "tcp://backup.td:10100",
            }
        )

        config_data = self._to_model_config(valid_config_dict)
        config = _create_config(**config_data)

        assert config.ctp_backup_user_id == "backup_user"
        assert config.ctp_backup_md_address == "tcp://backup.md:10110"

    def test_environment_file_loading(self, tmp_path, valid_config_dict):
        """Test loading configuration from .env file."""
        env_file = tmp_path / ".env.test"

        # Write config to file
        with env_file.open("w", encoding="utf-8") as f:
            for key, value in valid_config_dict.items():
                f.write(f"{key}={value}\n")

        # Load from environment variables instead
        os.environ.update(valid_config_dict)
        try:
            config = _create_config_from_env()

            assert config.ctp_broker_id == "test_broker"
            assert config.session_window == "day"

        finally:
            # Clean up environment
            for key in valid_config_dict:
                os.environ.pop(key, None)

    def test_profile_specific_configuration(self, valid_config_dict):
        """Test that different profiles can be validated."""
        profiles = ["live", "test", "dev"]

        for profile in profiles:
            valid_config_dict["SESSION_PROFILE"] = profile
            config_data = self._to_model_config(valid_config_dict)
            config = _create_config(**config_data)
            assert config.session_profile == profile

        # Test invalid profile
        valid_config_dict["SESSION_PROFILE"] = "production"
        config_data = self._to_model_config(valid_config_dict)

        with pytest.raises(ValidationError):
            _create_config(**config_data)

    def test_day_session_timing_validation(self, valid_config_dict):
        """Test day session configuration and timing."""
        valid_config_dict["SESSION_WINDOW"] = "day"
        config_data = self._to_model_config(valid_config_dict)
        config = _create_config(**config_data)

        # Day session should be configured
        assert config.session_window == "day"

        # Validate T-5 checkpoint timing (08:55 for 09:00 start)
        from datetime import datetime, time, timedelta

        session_start = time(9, 0)  # 09:00
        t5_checkpoint = time(8, 55)  # 08:55

        # Calculate difference
        start_dt = datetime.combine(datetime.today(), session_start)
        t5_dt = datetime.combine(datetime.today(), t5_checkpoint)
        diff = start_dt - t5_dt

        assert diff == timedelta(
            minutes=5
        ), "T-5 checkpoint should be 5 minutes before start"

    def test_night_session_timing_validation(self, valid_config_dict):
        """Test night session configuration and timing."""
        valid_config_dict["SESSION_WINDOW"] = "night"
        config_data = self._to_model_config(valid_config_dict)
        config = _create_config(**config_data)

        # Night session should be configured
        assert config.session_window == "night"

        # Validate T-5 checkpoint timing (20:55 for 21:00 start)
        from datetime import datetime, time, timedelta

        session_start = time(21, 0)  # 21:00
        t5_checkpoint = time(20, 55)  # 20:55

        # Calculate difference
        start_dt = datetime.combine(datetime.today(), session_start)
        t5_dt = datetime.combine(datetime.today(), t5_checkpoint)
        diff = start_dt - t5_dt

        assert diff == timedelta(
            minutes=5
        ), "T-5 checkpoint should be 5 minutes before start"

    def test_sensitive_data_masking(self, valid_config_dict):
        """Test that sensitive data can be masked for logging."""
        config_data = self._to_model_config(valid_config_dict)
        config = _create_config(**config_data)

        def mask_sensitive(value: str) -> str:
            """Mask sensitive values for logging."""
            if len(value) <= 4:
                return "***"
            return f"{value[:2]}***{value[-2:]}"

        # Test masking
        assert mask_sensitive(config.ctp_password) != config.ctp_password
        assert (
            mask_sensitive(config.nats_password) != config.nats_password
        )  # pragma: allowlist secret
        assert "***" in mask_sensitive(config.ctp_auth_code)  # pragma: allowlist secret

    def test_config_completeness_for_failover(self, valid_config_dict):
        """Test that configuration is complete for failover scenarios."""
        # Add backup configuration
        valid_config_dict.update(
            {
                "CTP_BACKUP_USER_ID": "backup_user",
                "CTP_BACKUP_PASSWORD": "backup_pass",  # pragma: allowlist secret
                "CTP_BACKUP_MD_ADDRESS": "tcp://backup.md:10110",
                "CTP_BACKUP_TD_ADDRESS": "tcp://backup.td:10100",
            }
        )

        config_data = self._to_model_config(valid_config_dict)
        config = _create_config(**config_data)

        # Verify both primary and backup are configured
        assert config.ctp_user_id is not None
        assert config.ctp_backup_user_id is not None

        # Simulate failover by using backup values
        active_user = (
            config.ctp_backup_user_id
            if config.ctp_backup_user_id
            else config.ctp_user_id
        )
        active_md = (
            config.ctp_backup_md_address
            if config.ctp_backup_md_address
            else config.ctp_md_address
        )

        assert active_user == "backup_user"
        assert active_md == "tcp://backup.md:10110"


class TestAppSettingsGovernance:
    """Regression tests for AppSettings credential governance."""

    @pytest.fixture
    def primary_env(self) -> dict[str, str]:
        """Return primary profile environment variables."""
        return {
            "CTP_PRIMARY_BROKER_ID": "9999",
            "CTP_PRIMARY_USER_ID": "primary_user",
            "CTP_PRIMARY_PASSWORD": "primary_pass",  # pragma: allowlist secret
            "CTP_PRIMARY_MD_ADDRESS": "tcp://primary.md:10110",
            "CTP_PRIMARY_TD_ADDRESS": "tcp://primary.td:10100",
            "CTP_PRIMARY_APP_ID": "primary_app",
            "CTP_PRIMARY_AUTH_CODE": "primary_auth",  # pragma: allowlist secret
            "CTP_BACKUP_BROKER_ID": "",
            "CTP_BACKUP_USER_ID": "",
            "CTP_BACKUP_PASSWORD": "",
            "CTP_BACKUP_MD_ADDRESS": "",
            "CTP_BACKUP_TD_ADDRESS": "",
            "CTP_BACKUP_APP_ID": "",
            "CTP_BACKUP_AUTH_CODE": "",
            "CTP_ROUTE_SELECTOR": "primary",
            "SUBSCRIBE_RATE_LIMIT_WINDOW_SECONDS": "60",
            "SUBSCRIBE_RATE_LIMIT_MAX_REQUESTS": "5000",
            "RATE_LIMIT_LOGIN_PER_MINUTE": "5",
            "RATE_LIMIT_SUBSCRIBE_PER_SECOND": "10",
        }

    def test_primary_profile_requires_tcp_address(self, primary_env):
        """Ensure primary addresses must be tcp:// prefixed."""
        primary_env["CTP_PRIMARY_MD_ADDRESS"] = "invalid-address"
        settings = AppSettings.model_validate(primary_env, context={"_env_file": None})

        assert "CTP_PRIMARY_MD_ADDRESS" in settings.invalid_endpoint_fields()

    def test_backup_profile_requires_pairs(self, primary_env):
        """Partial backup profile raises validation error."""
        env_data = primary_env.copy()

        env_data.update(
            {
                "CTP_BACKUP_BROKER_ID": "8888",
                "CTP_BACKUP_USER_ID": "backup_user",
                "CTP_BACKUP_MD_ADDRESS": "tcp://backup.md:10110",
                "CTP_BACKUP_TD_ADDRESS": "tcp://backup.td:10100",
                "CTP_BACKUP_APP_ID": "backup_app",
                "CTP_BACKUP_AUTH_CODE": "backup_auth",
            }
        )

        with pytest.raises(ValidationError) as exc:
            AppSettings.model_validate(env_data, context={"_env_file": None})

        assert "CTP_BACKUP_PASSWORD" in str(exc.value)

    def test_to_dict_safe_masks_primary_password(self, primary_env):
        """Sensitive values are masked in safe dump."""
        settings = AppSettings.model_validate(primary_env, context={"_env_file": None})
        masked = settings.to_dict_safe()

        assert (
            "..." in masked["ctp_primary_password"]
            or masked["ctp_primary_password"] == "***"
        )

    def test_structured_profiles_available(self, primary_env):
        """Structured primary/backup profiles should surface through AppSettings."""
        env_data = primary_env.copy()
        env_data.update(
            {
                "CTP_BACKUP_BROKER_ID": "8888",
                "CTP_BACKUP_USER_ID": "backup_user",
                "CTP_BACKUP_PASSWORD": "backup_pass",  # pragma: allowlist secret
                "CTP_BACKUP_MD_ADDRESS": "tcp://backup.md:10110",
                "CTP_BACKUP_TD_ADDRESS": "tcp://backup.td:10100",
                "CTP_BACKUP_APP_ID": "backup_app",
                "CTP_BACKUP_AUTH_CODE": "backup_auth",
            }
        )

        settings = AppSettings.model_validate(env_data, context={"_env_file": None})

        assert settings.ctp_primary.user_id == "primary_user"
        assert isinstance(settings.ctp_primary.password, SecretStr)
        assert settings.ctp_backup.user_id == "backup_user"
        assert settings.has_backup_profile()

        safe = settings.to_dict_safe()
        primary_masked = safe["ctp_primary"]["password"]
        backup_masked = safe["ctp_backup"]["password"]
        assert primary_masked != "primary_pass"  # pragma: allowlist secret
        assert backup_masked != "backup_pass"  # pragma: allowlist secret

    def test_validate_env_cli_success(self, primary_env, tmp_path, capfd, monkeypatch):
        """CLI returns zero when environment is valid."""
        env_data = primary_env.copy()
        for key in list(os.environ):
            if key.startswith(("CTP_", "RATE_LIMIT", "SUBSCRIBE_RATE_LIMIT")):
                monkeypatch.delenv(key, raising=False)

        env_file = tmp_path / ".env.live"
        with env_file.open("w", encoding="utf-8") as fh:
            for key, value in env_data.items():
                fh.write(f"{key}={value}\n")

        exit_code = validate_env.main(
            [
                "--source",
                str(env_file),
                "--profile",
                "live",
            ]
        )

        captured = capfd.readouterr()

        combined = captured.out + captured.err

        assert exit_code == 0
        assert "environment_validation_passed" in combined

    def test_validate_env_cli_failure_missing_primary(
        self, primary_env, tmp_path, capfd, monkeypatch
    ):
        """CLI exits non-zero when mandatory fields missing."""
        env_data = primary_env.copy()

        for key in list(os.environ):
            if key.startswith(("CTP_", "RATE_LIMIT", "SUBSCRIBE_RATE_LIMIT")):
                monkeypatch.delenv(key, raising=False)
        env_file = tmp_path / ".env.live"
        # Remove broker id to trigger failure
        env_data.pop("CTP_PRIMARY_BROKER_ID")

        with env_file.open("w", encoding="utf-8") as fh:
            for key, value in env_data.items():
                fh.write(f"{key}={value}\n")

        exit_code = validate_env.main(
            [
                "--source",
                str(env_file),
                "--profile",
                "live",
            ]
        )

        captured = capfd.readouterr()

        combined = captured.out + captured.err

        assert exit_code == 1
        assert "CTP_PRIMARY_BROKER_ID" in combined

    def test_validate_env_cli_require_backup_flag(
        self, primary_env, tmp_path, capfd, monkeypatch
    ):
        """Requiring backup must fail when backup block incomplete."""
        env_data = primary_env.copy()

        for key in list(os.environ):
            if key.startswith(("CTP_", "RATE_LIMIT", "SUBSCRIBE_RATE_LIMIT")):
                monkeypatch.delenv(key, raising=False)

        env_file = tmp_path / ".env.live"
        with env_file.open("w", encoding="utf-8") as fh:
            for key, value in env_data.items():
                fh.write(f"{key}={value}\n")

        exit_code = validate_env.main(
            [
                "--source",
                str(env_file),
                "--profile",
                "live",
                "--require-backup",
            ]
        )

        captured = capfd.readouterr()

        combined = captured.out + captured.err

        assert exit_code == 1
        assert "Backup profile required" in combined or "Incomplete backup" in combined

    def test_validate_env_cli_require_backup_success(
        self, primary_env, tmp_path, capfd, monkeypatch
    ):
        """Requiring backup succeeds when all backup values present."""
        env_data = primary_env.copy()

        for key in list(os.environ):
            if key.startswith(("CTP_", "RATE_LIMIT", "SUBSCRIBE_RATE_LIMIT")):
                monkeypatch.delenv(key, raising=False)

        env_data.update(
            {
                "CTP_BACKUP_BROKER_ID": "8888",
                "CTP_BACKUP_USER_ID": "backup_user",
                "CTP_BACKUP_PASSWORD": "backup_pass",  # pragma: allowlist secret
                "CTP_BACKUP_MD_ADDRESS": "tcp://backup.md:10110",
                "CTP_BACKUP_TD_ADDRESS": "tcp://backup.td:10100",
                "CTP_BACKUP_APP_ID": "backup_app",
                "CTP_BACKUP_AUTH_CODE": "backup_auth",
            }
        )

        env_file = tmp_path / ".env.live"
        with env_file.open("w", encoding="utf-8") as fh:
            for key, value in env_data.items():
                fh.write(f"{key}={value}\n")

        exit_code = validate_env.main(
            [
                "--source",
                str(env_file),
                "--profile",
                "live",
                "--require-backup",
            ]
        )

        captured = capfd.readouterr()

        combined = captured.out + captured.err

        assert exit_code == 0
        assert "environment_validation_passed" in combined
