"""Tests for credlens.logging_config."""

from __future__ import annotations

import logging

import pytest

from credlens.logging_config import configure_logging, get_logger


def test_configure_logging_sets_level() -> None:
    configure_logging("DEBUG")
    logger = logging.getLogger("credlens")

    assert logger.level == logging.DEBUG
    assert len(logger.handlers) == 1


def test_configure_logging_is_idempotent() -> None:
    configure_logging("INFO")
    configure_logging("WARNING")
    logger = logging.getLogger("credlens")

    assert logger.level == logging.WARNING
    assert len(logger.handlers) == 1


def test_configure_logging_rejects_invalid_level() -> None:
    with pytest.raises(ValueError, match="Invalid log level"):
        configure_logging("NOT_A_LEVEL")


def test_get_logger_namespaces_under_credlens() -> None:
    logger = get_logger("my_module")

    assert logger.name == "credlens.my_module"
