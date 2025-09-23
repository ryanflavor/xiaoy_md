"""Unit tests for configuration security features."""

from src.config import AppSettings


class TestConfigurationSecurity:
    """Test configuration security features."""

    def test_to_dict_safe_masks_nats_url(self):
        """Test that NATS URL is masked in safe output."""
        settings = AppSettings.model_construct(
            nats_url="nats://secret-host:4222",
            nats_cluster_id="secret-cluster-id",
            nats_client_id="secret-client-id",
        )
        safe_dict = settings.to_dict_safe()

        assert safe_dict["nats_url"] == "nats...22"
        assert "secret-host" not in safe_dict["nats_url"]

    def test_to_dict_safe_masks_cluster_id(self):
        """Test that cluster ID is masked in safe output."""
        settings = AppSettings.model_construct(
            nats_cluster_id="secret-cluster-id",
        )
        safe_dict = settings.to_dict_safe()

        assert safe_dict["nats_cluster_id"] == "secr...id"
        assert "secret-cluster" not in safe_dict["nats_cluster_id"]

    def test_to_dict_safe_masks_client_id(self):
        """Test that client ID is masked in safe output."""
        settings = AppSettings.model_construct(
            nats_client_id="secret-client-id",
        )
        safe_dict = settings.to_dict_safe()

        assert safe_dict["nats_client_id"] == "secr...id"
        assert "secret-client" not in safe_dict["nats_client_id"]

    def test_to_dict_safe_short_values(self):
        """Test that short sensitive values are fully masked."""
        settings = AppSettings.model_construct(
            nats_url="nats",
            nats_cluster_id="abc",
            nats_client_id="xyz",
        )
        safe_dict = settings.to_dict_safe()

        assert safe_dict["nats_url"] == "***"
        assert safe_dict["nats_cluster_id"] == "***"
        assert safe_dict["nats_client_id"] == "***"

    def test_to_dict_safe_preserves_non_sensitive(self):
        """Test that non-sensitive fields are not masked."""
        settings = AppSettings.model_construct(
            app_name="test-app",
            app_version="1.2.3",
            environment="production",
            debug=True,
            log_level="DEBUG",
        )
        safe_dict = settings.to_dict_safe()

        assert safe_dict["app_name"] == "test-app"
        assert safe_dict["app_version"] == "1.2.3"
        assert safe_dict["environment"] == "production"
        assert safe_dict["debug"] is True
        assert safe_dict["log_level"] == "DEBUG"

    def test_to_dict_returns_full_values(self):
        """Test that regular to_dict returns full values."""
        settings = AppSettings.model_construct(
            nats_url="nats://secret-host:4222",
            nats_cluster_id="cluster-123",
            nats_client_id="client-456",
        )
        full_dict = settings.to_dict()

        assert full_dict["nats_url"] == "nats://secret-host:4222"
        assert full_dict["nats_cluster_id"] == "cluster-123"
        assert full_dict["nats_client_id"] == "client-456"
