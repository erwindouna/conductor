"""Tests for the logging configuration helper."""

from __future__ import annotations

import importlib
import logging
import sys

import pytest


def test_setup_logging(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simple test to test the setup_logging function."""
    monkeypatch.setenv("LOG_LEVEL", "INFO")

    sys.modules.pop("conductor.logger", None)
    clog = importlib.import_module("conductor.logger")
    clog = importlib.reload(clog)
    clog.setup_logging()

    assert logging.getLogger("uvicorn").level == logging.INFO
    assert logging.getLogger("uvicorn.error").level == logging.INFO
    assert logging.getLogger("uvicorn.access").level == logging.WARNING
