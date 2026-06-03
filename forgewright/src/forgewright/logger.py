"""Loguru setup: console + file + (optional) JSON sinks."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from loguru import logger

__all__ = ["logger", "setup_logging"]


def setup_logging(log_dir: str | None = None, level: str = "INFO") -> None:
    """Configure loguru. Idempotent: safe to call multiple times."""
    logger.remove()
    logger.add(
        sys.stderr,
        level=level,
        format=(
            "<green>{time:HH:mm:ss}</green> | "
            "<level>{level: <7}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
            "<level>{message}</level>"
        ),
        colorize=sys.stderr.isatty(),
        backtrace=True,
        diagnose=False,
    )
    if log_dir:
        path = Path(log_dir)
        path.mkdir(parents=True, exist_ok=True)
        log_file = path / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        logger.add(
            str(log_file),
            level=level,
            rotation="100 MB",
            retention="14 days",
            compression="zip",
            enqueue=True,
        )


# Configure on import with sane defaults.
setup_logging()
