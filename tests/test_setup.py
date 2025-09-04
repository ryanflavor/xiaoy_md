"""Test to verify project setup is correct."""

from pathlib import Path
import sys

import src.adapters
import src.application
from src.config import settings
import src.domain


def test_python_version():
    """Verify Python 3.13 is being used."""
    required_major = 3
    required_minor = 13
    assert sys.version_info.major == required_major
    assert sys.version_info.minor == required_minor


def test_project_structure():
    """Verify project structure exists."""
    required_dirs = [
        "src/domain",
        "src/application",
        "src/adapters",
        "tests/unit",
        "tests/integration",
        "scripts",
    ]

    for dir_path in required_dirs:
        assert Path(dir_path).exists(), f"Missing directory: {dir_path}"


def test_config_import():
    """Verify config can be imported."""
    assert settings.app_name == "market-data-service"
    assert settings.app_version == "0.1.0"


def test_architecture_layers():
    """Verify architecture layers can be imported."""
    # Imports moved to top of file

    assert src.domain.__doc__ is not None
    assert src.application.__doc__ is not None
    assert src.adapters.__doc__ is not None
