"""Application configuration module."""

import os
from pathlib import Path
from typing import Any, Dict

from pydantic import BaseModel, Field
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
    host: str = Field(default="0.0.0.0", description="Server host")
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

    def to_dict(self) -> Dict[str, Any]:
        """Convert settings to dictionary."""
        return self.model_dump()


# Global settings instance
settings = AppSettings()


def get_settings() -> AppSettings:
    """Get application settings."""
    return settings
