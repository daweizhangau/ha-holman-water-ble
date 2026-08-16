"""Pytest configuration for Holman Water BLE tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure the repo root is on sys.path so that `custom_components` is importable.
# This is needed when pytest is invoked from the repo root (CI, etc.).
_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))


def pytest_configure(config):
    """Configure pytest markers."""
    config.addinivalue_line(
        "markers",
        "integration: mark test as an integration test requiring a real BLE device",
    )
