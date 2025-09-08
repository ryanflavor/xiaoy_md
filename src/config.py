"""Application configuration module."""

from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    """Application settings with environment variable support."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

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
        default="nats://localhost:4222", description="NATS server URL"
    )
    nats_cluster_id: str = Field(
        default="market-data-cluster", description="NATS cluster ID"
    )
    nats_client_id: str = Field(
        default="market-data-service", description="NATS client ID"
    )
    nats_user: str | None = Field(
        default=None, description="NATS username for authentication"
    )
    nats_password: str | None = Field(
        default=None, description="NATS password for authentication"
    )
    nats_health_check_subject: str = Field(
        default="health.check", description="NATS health check subject"
    )

    # Logging settings
    log_level: str = Field(default="INFO", description="Logging level")
    log_format: str = Field(default="json", description="Log format (json or text)")

    @property
    def is_production(self) -> bool:
        """Check if running in production environment."""
        return self.environment.lower() == "production"

    @property
    def is_development(self) -> bool:
        """Check if running in development environment."""
        return self.environment.lower() == "development"

    def to_dict(self) -> dict[str, Any]:
        """Convert settings to dictionary."""
        return self.model_dump()

    def to_dict_safe(self) -> dict[str, Any]:
        """Convert settings to dictionary with sensitive fields masked."""
        data = self.model_dump()
        # Mask sensitive fields
        sensitive_fields = [
            "nats_url",
            "nats_cluster_id",
            "nats_client_id",
            "nats_user",
            "nats_password",
        ]
        for field in sensitive_fields:
            if data.get(field):
                # Keep first and last few chars visible for debugging
                value = str(data[field])
                min_mask_length = 8
                if len(value) > min_mask_length:
                    data[field] = f"{value[:4]}...{value[-2:]}"
                else:
                    data[field] = "***"
        return data


# Global settings instance
settings = AppSettings()


def get_settings() -> AppSettings:
    """Get application settings."""
    return settings
