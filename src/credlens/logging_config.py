"""Centralized logging configuration for CredLens.

Foundation phase: a single, idempotent entry point that configures the
`credlens` logger tree. Future phases (ingestion, ETL, modeling) should
call `get_logger(__name__)` rather than using `print` or the root logger
directly.
"""

from __future__ import annotations

import logging

DEFAULT_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"

_VALID_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


def configure_logging(level: str = "INFO", fmt: str = DEFAULT_FORMAT) -> None:
    """Configure the `credlens` logger tree.

    Idempotent: calling this more than once reconfigures the existing
    handler instead of stacking duplicate handlers, which matters because
    the CLI may call it on every invocation.

    Raises:
        ValueError: if `level` is not a recognized logging level name.
    """
    normalized = level.upper()
    if normalized not in _VALID_LEVELS:
        raise ValueError(f"Invalid log level {level!r}. Expected one of {sorted(_VALID_LEVELS)}.")

    logger = logging.getLogger("credlens")
    logger.setLevel(normalized)

    for handler in list(logger.handlers):
        logger.removeHandler(handler)

    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(fmt))
    logger.addHandler(handler)
    logger.propagate = False


def get_logger(name: str) -> logging.Logger:
    """Return a logger namespaced under `credlens.<name>`."""
    return logging.getLogger(f"credlens.{name}")
