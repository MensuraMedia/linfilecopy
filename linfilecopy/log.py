"""Application logging: stderr plus a rotating file in the state directory."""
from __future__ import annotations

import logging
import logging.handlers

from linfilecopy import paths

LOGGER_NAME = "linfilecopy"


def setup_logging(level: int = logging.INFO, to_file: bool = True) -> logging.Logger:
    """Configure and return the package logger. Safe to call more than once."""
    logger = logging.getLogger(LOGGER_NAME)
    if logger.handlers:
        logger.setLevel(level)
        return logger
    logger.setLevel(level)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    logger.addHandler(stream)
    if to_file:
        try:
            paths.logs_dir().mkdir(parents=True, exist_ok=True)
            handler = logging.handlers.RotatingFileHandler(
                paths.state_dir() / "linfilecopy.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
            )
            handler.setFormatter(fmt)
            logger.addHandler(handler)
        except OSError as exc:  # read-only home, full disk: keep going with stderr only
            logger.warning("file logging disabled: %s", exc)
    return logger


def get_logger(name: str) -> logging.Logger:
    """Return a child logger, e.g. ``get_logger(__name__)``."""
    return logging.getLogger(name if name.startswith(LOGGER_NAME) else f"{LOGGER_NAME}.{name}")
