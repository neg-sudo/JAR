"""Logging setup with rotation and safe repeated calls."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from .config import Config


def configure_logging(config: Config, *, verbose: bool = False, quiet: bool = False) -> logging.Logger:
    """Configure the ``jar`` logger once per process.

    File logging is always on (rotating); console logging is only added for
    verbose runs so JSON output stays clean.
    """
    logger = logging.getLogger("jar")
    level_name = str(config.data.get("log_level") or "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    if verbose:
        level = logging.DEBUG
    elif quiet:
        level = logging.ERROR
    logger.setLevel(level)
    logger.propagate = False

    for handler in list(logger.handlers):
        if getattr(handler, "_jar_handler", False):
            logger.removeHandler(handler)
            try:
                handler.close()
            except Exception:  # noqa: BLE001
                pass

    try:
        config.paths.log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            config.paths.log_file,
            maxBytes=int(config.data.get("log_max_bytes") or 1048576),
            backupCount=int(config.data.get("log_backups") or 3),
            encoding="utf-8",
        )
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
        )
        file_handler._jar_handler = True  # type: ignore[attr-defined]
        logger.addHandler(file_handler)
    except OSError:
        pass

    if verbose:
        console = logging.StreamHandler()
        console.setFormatter(logging.Formatter("%(levelname)-7s %(message)s"))
        console._jar_handler = True  # type: ignore[attr-defined]
        logger.addHandler(console)

    return logger


def shutdown_logging() -> None:
    """Close JAR's logging handlers.

    Windows keeps log files locked while a handler is open, which prevents
    temporary directories (and uninstalls) from removing them.  Call this at
    process shutdown and in test teardown.
    """
    logger = logging.getLogger("jar")
    for handler in list(logger.handlers):
        if getattr(handler, "_jar_handler", False):
            logger.removeHandler(handler)
            try:
                handler.close()
            except Exception:  # noqa: BLE001
                pass
