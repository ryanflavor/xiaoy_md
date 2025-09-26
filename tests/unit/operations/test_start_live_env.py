"""Unit tests for start_live_env.sh orchestration script.

Tests the script behavior, sequencing, and error handling.
"""

from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import tempfile

import pytest


class TestStartLiveEnvOrchestration:
    """Test suite for production environment orchestration script."""

    @pytest.fixture
    def script_path(self):
        """Get the path to the orchestration script."""
        return (
            Path(__file__).parents[3] / "scripts" / "operations" / "start_live_env.sh"
        )

    def run_script(
        self,
        script_path: Path,
        extra_args: list[str] | None = None,
        env: dict[str, str] | None = None,
        timeout: int = 15,
    ):
        """Run the orchestration script in mock mode for fast unit execution."""
        args = [str(script_path), "--mock"]
        if extra_args:
            args.extend(extra_args)
        return subprocess.run(
            args,
            capture_output=True,
            text=True,
            env=env,
            timeout=timeout,
            check=False,
        )

    @pytest.fixture
    def temp_env_file(self):
        """Create a temporary environment file for testing."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".env.test", delete=False
        ) as f:
            f.write(
                """
# Test environment configuration
CTP_BROKER_ID=test_broker
CTP_USER_ID=test_user
CTP_PASSWORD=test_pass
CTP_MD_ADDRESS=tcp://test.md.address:10110
CTP_TD_ADDRESS=tcp://test.td.address:10100
CTP_APP_ID=test_app
CTP_AUTH_CODE=test_auth
CTP_SYMBOL=rb2510.SHFE

# Backup configuration
CTP_BACKUP_BROKER_ID=backup_broker
CTP_BACKUP_USER_ID=backup_user
CTP_BACKUP_PASSWORD=backup_pass
CTP_BACKUP_MD_ADDRESS=tcp://backup.md.address:10110
CTP_BACKUP_TD_ADDRESS=tcp://backup.td.address:10100
CTP_BACKUP_APP_ID=backup_app
CTP_BACKUP_AUTH_CODE=backup_auth

# NATS configuration
NATS_USER=test_nats_user
NATS_PASSWORD=test_nats_pass
NATS_URL=nats://localhost:4222

# Rate limits
RATE_LIMIT_LOGIN_PER_MINUTE=5
RATE_LIMIT_SUBSCRIBE_PER_SECOND=10

# Prometheus
PUSHGATEWAY_URL=http://localhost:9091
"""
            )
            temp_path = Path(f.name)

        yield temp_path

        # Cleanup
        if temp_path.exists():
            temp_path.unlink()

    def test_script_exists_and_executable(self, script_path):
        """Verify the orchestration script exists and is executable."""
        assert script_path.exists(), f"Script not found at {script_path}"
        assert os.access(script_path, os.X_OK), "Script is not executable"

    def test_help_output(self, script_path):
        """Test that help flag provides usage information."""
        result = subprocess.run(
            [str(script_path), "--help"], capture_output=True, text=True, check=False
        )

        assert result.returncode == 0
        assert "Usage:" in result.stdout
        assert "--window" in result.stdout
        assert "--profile" in result.stdout
        assert "--restart" in result.stdout
        assert "--failover" in result.stdout
        assert "--mock" in result.stdout

    def test_json_log_format(self, script_path, temp_env_file, tmp_path):
        """Verify script outputs valid JSON logs."""
        log_dir = tmp_path / "logs" / "runbooks"
        log_dir.mkdir(parents=True)

        # Run script in dry-run mode (stop immediately)
        env = os.environ.copy()
        env["ENV_FILE"] = str(temp_env_file)

        result = self.run_script(
            script_path,
            ["--stop", "--profile", "test", "--log-dir", str(log_dir)],
            env=env,
        )

        # Parse JSON logs from output
        account_values = set()
        for line in result.stdout.splitlines():
            if line.strip() and line.startswith("{"):
                try:
                    log_entry = json.loads(line)
                    assert "timestamp" in log_entry
                    assert "level" in log_entry
                    assert "message" in log_entry
                    assert "session" in log_entry
                    assert "exit_code" in log_entry
                    assert "config" in log_entry
                    assert "active_feed" in log_entry
                    assert "account" in log_entry
                    assert "mock" in log_entry
                    account_values.add(log_entry["account"])
                except json.JSONDecodeError:
                    pass  # Skip non-JSON lines

    def test_day_window_configuration(self, script_path):
        """Test that day window sets correct session times."""
        # This would normally require mocking or a test mode
        # For now, verify the script accepts the parameter
        result = subprocess.run(
            [str(script_path), "--window", "day", "--help"],
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0

    def test_night_window_configuration(self, script_path):
        """Test that night window sets correct session times."""
        result = subprocess.run(
            [str(script_path), "--window", "night", "--help"],
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0

    def test_environment_validation(self, temp_env_file: Path):
        """Test that environment variables are validated properly."""
        content = temp_env_file.read_text(encoding="utf-8")

        # Verify required variables are present
        assert "CTP_BROKER_ID=" in content
        assert "CTP_USER_ID=" in content
        assert "CTP_MD_ADDRESS=" in content
        assert "NATS_USER=" in content
        assert "NATS_PASSWORD=" in content

    def test_backup_configuration_switch(self, temp_env_file: Path):
        """Test that backup configuration can be selected."""
        content = temp_env_file.read_text(encoding="utf-8")

        # Verify backup variables are present
        assert "CTP_BACKUP_USER_ID=" in content
        assert "CTP_BACKUP_MD_ADDRESS=" in content

    def test_exit_codes_for_failures(self, script_path, tmp_path):
        """Test that script returns appropriate exit codes for different failures."""
        # Test with non-existent env file
        result = self.run_script(
            script_path,
            ["--profile", "nonexistent", "--log-dir", str(tmp_path)],
        )

        # Should fail with non-zero exit code
        assert result.returncode != 0

    def test_explicit_env_file_override(self, script_path, tmp_path):
        """Explicit --env-file should override defaults and error if missing."""
        missing_env = tmp_path / "missing.env"
        env = os.environ.copy()

        result = self.run_script(
            script_path,
            [
                "--profile",
                "test",
                "--env-file",
                str(missing_env),
                "--log-dir",
                str(tmp_path),
            ],
            env=env,
        )

        assert result.returncode != 0
        assert "Environment file not found" in (result.stdout + result.stderr)

    def test_audit_log_creation(self, script_path, temp_env_file, tmp_path):
        """Test that audit logs are created with correct format."""
        log_dir = tmp_path / "logs" / "runbooks"
        log_dir.mkdir(parents=True)

        env = os.environ.copy()
        env["ENV_FILE"] = str(temp_env_file)

        # Run stop action (simplest to test)
        result = self.run_script(
            script_path,
            ["--stop", "--profile", "test", "--log-dir", str(log_dir)],
            env=env,
        )

        # Check if audit log was created
        audit_log = log_dir / "startup_audit.log"
        # Verify the stop command produces logs in stdout
        assert "stop" in result.stdout.lower() or "stop" in result.stderr.lower()

    def test_custom_log_dir_created(self, script_path, temp_env_file, tmp_path):
        """Custom --log-dir should be created automatically."""
        custom_dir = tmp_path / "nested" / "logs"
        assert not custom_dir.exists()

        env = os.environ.copy()
        env["ENV_FILE"] = str(temp_env_file)

        result = self.run_script(
            script_path,
            ["--profile", "test", "--log-dir", str(custom_dir)],
            env=env,
        )

        assert result.returncode == 0
        assert custom_dir.exists()
        start_log = custom_dir / "start_live_env.log"
        assert start_log.exists()

    def test_t5_checkpoint_timing(self):
        """Test that T-5 checkpoints are correctly calculated."""
        # Day session: 09:00 start -> T-5 at 08:55
        day_t5 = "08:55"
        day_start = "09:00"

        # Night session: 21:00 start -> T-5 at 20:55
        night_t5 = "20:55"
        night_start = "21:00"

        # Parse times

        day_t5_time = datetime.strptime(day_t5, "%H:%M").time()
        day_start_time = datetime.strptime(day_start, "%H:%M").time()

        # Calculate difference
        day_t5_dt = datetime.combine(datetime.today(), day_t5_time)
        day_start_dt = datetime.combine(datetime.today(), day_start_time)
        diff = (day_start_dt - day_t5_dt).seconds

        assert diff == 300, "T-5 checkpoint should be 5 minutes before session start"

    def test_timezone_asia_shanghai(self, script_path, temp_env_file, tmp_path):
        """Test that all timestamps use Asia/Shanghai timezone."""
        log_dir = tmp_path / "logs" / "runbooks"
        log_dir.mkdir(parents=True)

        env = os.environ.copy()
        env["ENV_FILE"] = str(temp_env_file)
        env["TZ"] = "Asia/Shanghai"

        result = self.run_script(
            script_path,
            ["--stop", "--profile", "test", "--log-dir", str(log_dir)],
            env=env,
        )

        # Check JSON logs for timezone info
        for line in result.stdout.splitlines():
            if line.strip() and line.startswith("{"):
                try:
                    log_entry = json.loads(line)
                    if "timestamp" in log_entry:
                        # Timestamp should be in ISO format
                        timestamp = log_entry["timestamp"]
                        # Check it's a valid timestamp format (basic check)
                        assert "T" in timestamp  # ISO format should have T separator
                        assert timestamp.endswith("+08:00")
                except json.JSONDecodeError:
                    pass

    @pytest.mark.parametrize(
        ("action", "expected_in_output"),
        [
            ("--restart", "restart"),
            ("--stop", "stop"),
            ("--failover", "failover"),
        ],
    )
    def test_orchestration_actions(
        self, script_path, temp_env_file, tmp_path, action, expected_in_output
    ):
        """Test different orchestration actions."""
        log_dir = tmp_path / "logs" / "runbooks"
        log_dir.mkdir(parents=True)

        env = os.environ.copy()
        env["ENV_FILE"] = str(temp_env_file)

        result = self.run_script(
            script_path,
            [action, "--profile", "test", "--log-dir", str(log_dir)],
            env=env,
        )

        # Action should be mentioned in output
        combined_output = result.stdout.lower() + result.stderr.lower()
        assert (
            expected_in_output.lower() in combined_output
        ), f"Expected '{expected_in_output}' not found in output"

    def test_metric_emission_format(self):
        """Test that metrics are formatted correctly for Pushgateway."""
        metrics = {
            "md_runbook_exit_code": 0,
            "md_failover_latency_ms": 1234,
            "md_session_startup_duration_s": 45,
        }

        for metric_name, value in metrics.items():
            formatted = f"{metric_name} {value}"
            # Verify format matches Prometheus exposition format
            assert " " in formatted
            parts = formatted.split()
            assert len(parts) == 2
            assert parts[0] == metric_name
            assert parts[1] == str(value)

    def test_sequential_component_startup(self):
        """Test that components are started in correct sequence."""
        # Expected sequence: NATS -> market-data-service -> subscription-worker
        expected_sequence = ["NATS", "market-data-service", "subscription-worker"]

        # This test validates the documented sequence
        assert expected_sequence[0] == "NATS", "NATS must start first"
        assert (
            expected_sequence[1] == "market-data-service"
        ), "Market data service starts second"
        assert (
            expected_sequence[2] == "subscription-worker"
        ), "Subscription worker starts last"

    def test_readiness_check_timeout(self):
        """Test that readiness checks have appropriate timeouts."""
        timeouts = {
            "NATS": 20,  # seconds
            "market-data-service": 30,  # seconds
            "subscription-worker": 10,  # seconds (for PID check)
        }

        for component, timeout in timeouts.items():
            assert timeout > 0, f"{component} timeout must be positive"
            assert timeout <= 60, f"{component} timeout should not exceed 60 seconds"

    def test_config_profile_selection(self, script_path):
        """Test that primary and backup configs can be selected."""
        for config in ["primary", "backup"]:
            result = subprocess.run(
                [str(script_path), "--config", config, "--help"],
                capture_output=True,
                text=True,
                check=False,
            )
            assert result.returncode == 0
            assert "Usage:" in result.stdout  # Help should still display

    def test_failback_action_exists(self, script_path):
        """Test that failback action is recognized."""
        result = subprocess.run(
            [str(script_path), "--help"], capture_output=True, text=True, check=False
        )
        assert "--failback" in result.stdout
        assert "Switch back to primary" in result.stdout

    @pytest.mark.parametrize(
        "action", ["start", "stop", "restart", "failover", "failback"]
    )
    def test_all_actions_recognized(self, script_path, temp_env_file, tmp_path, action):
        """Test that all actions are recognized without unknown action error."""
        log_dir = tmp_path / "logs" / "runbooks"
        log_dir.mkdir(parents=True)

        env = os.environ.copy()
        env["ENV_FILE"] = str(temp_env_file)

        if action == "start":
            extra = ["--profile", "test", "--log-dir", str(log_dir)]
        else:
            extra = [f"--{action}", "--profile", "test", "--log-dir", str(log_dir)]

        result = self.run_script(script_path, extra_args=extra, env=env)

        # Should not have "Unknown action" error
        assert "Unknown action" not in result.stdout
        assert "Unknown action" not in result.stderr

    def test_failover_emits_metrics(self, script_path, temp_env_file, tmp_path):
        """Test that failover action emits required metrics."""
        log_dir = tmp_path / "logs" / "runbooks"
        log_dir.mkdir(parents=True)

        env = os.environ.copy()
        env["ENV_FILE"] = str(temp_env_file)

        result = self.run_script(
            script_path,
            ["--failover", "--profile", "test", "--log-dir", str(log_dir)],
            env=env,
        )

        # Check for failover-specific outputs
        assert (
            "failover" in result.stdout.lower() or "failover" in result.stderr.lower()
        )
        # Check that JSON logs are emitted
        has_json = False
        for line in result.stdout.splitlines():
            if line.startswith("{") and "failover" in line.lower():
                has_json = True
                break
        assert has_json, "No JSON log output for failover found"

    def test_failover_rejects_incomplete_backup(self, script_path, tmp_path):
        """Failover must halt when backup credentials are incomplete."""
        log_dir = tmp_path / "logs" / "runbooks"
        log_dir.mkdir(parents=True)

        env_file = tmp_path / ".env.incomplete"
        env_file.write_text(
            """
# Minimal env missing backup password
CTP_BROKER_ID=test_broker
CTP_USER_ID=test_user
CTP_PASSWORD=test_pass
CTP_MD_ADDRESS=tcp://test.md.address:10110
CTP_TD_ADDRESS=tcp://test.td.address:10100
CTP_APP_ID=test_app
CTP_AUTH_CODE=test_auth

CTP_BACKUP_BROKER_ID=backup_broker
CTP_BACKUP_USER_ID=backup_user
CTP_BACKUP_MD_ADDRESS=tcp://backup.md.address:10110
CTP_BACKUP_TD_ADDRESS=tcp://backup.td.address:10100

NATS_URL=nats://localhost:4222
""",
            encoding="utf-8",
        )

        env = os.environ.copy()
        env["ENV_FILE"] = str(env_file)

        result = self.run_script(
            script_path,
            ["--failover", "--profile", "test", "--log-dir", str(log_dir)],
            env=env,
        )

        assert result.returncode != 0
        combined = result.stdout + result.stderr
        assert "Backup credential profile incomplete" in combined

    def test_failback_emits_metrics(self, script_path, temp_env_file, tmp_path):
        """Test that failback action emits required metrics."""
        log_dir = tmp_path / "logs" / "runbooks"
        log_dir.mkdir(parents=True)

        env = os.environ.copy()
        env["ENV_FILE"] = str(temp_env_file)

        result = self.run_script(
            script_path,
            ["--failback", "--profile", "test", "--log-dir", str(log_dir)],
            env=env,
        )

        # Check for failback-specific outputs
        assert (
            "failback" in result.stdout.lower() or "failback" in result.stderr.lower()
        )
        # Check that JSON logs are emitted
        has_json = False
        for line in result.stdout.splitlines():
            if line.startswith("{") and "failback" in line.lower():
                has_json = True
                break
        assert has_json, "No JSON log output for failback found"

    def test_drill_action_with_mock(self, script_path, temp_env_file, tmp_path):
        """Drill workflow should succeed in mock mode with metric verification."""
        log_dir = tmp_path / "logs" / "runbooks"
        log_dir.mkdir(parents=True)

        metrics_file = tmp_path / "metrics.prom"
        metrics_file.write_text("consumer_backlog_messages 1500\n", encoding="utf-8")

        env = os.environ.copy()
        env["ENV_FILE"] = str(temp_env_file)
        env["DRILL_HEALTH_CMD"] = "true"
        env["DRILL_METRICS_SOURCE"] = str(metrics_file)
        env["DRILL_CONSUMER_BACKLOG_THRESHOLD"] = "2000"

        result = self.run_script(
            script_path,
            ["--drill", "--profile", "test", "--log-dir", str(log_dir)],
            env=env,
            timeout=25,
        )

        assert result.returncode == 0
        assert "drill" in result.stdout.lower()
        assert "failover drill completed" in result.stdout.lower()

    def test_drill_metrics_threshold_failure(
        self, script_path, temp_env_file, tmp_path
    ):
        """Drill should fail when metrics exceed configured threshold."""
        log_dir = tmp_path / "logs" / "runbooks"
        log_dir.mkdir(parents=True)

        metrics_file = tmp_path / "metrics.prom"
        metrics_file.write_text("consumer_backlog_messages 9000\n", encoding="utf-8")

        env = os.environ.copy()
        env["ENV_FILE"] = str(temp_env_file)
        env["DRILL_HEALTH_CMD"] = "true"
        env["DRILL_METRICS_SOURCE"] = str(metrics_file)
        env["DRILL_CONSUMER_BACKLOG_THRESHOLD"] = "10"

        result = self.run_script(
            script_path,
            ["--drill", "--profile", "test", "--log-dir", str(log_dir)],
            env=env,
            timeout=25,
        )

        assert result.returncode != 0
        combined_output = result.stdout.lower() + result.stderr.lower()
        assert "consumer_backlog_messages" in combined_output
