"""Strukturirano beleženje za KIR/KPR → Minimax Studio (Cursor izdaja)."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any


LOGGER_NAME = "kirkpr_minimax"
DEFAULT_LOG_NAME = "KIRKPR_studio.log"


def app_dir() -> Path:
    return Path(__file__).resolve().parent


def default_log_path(base_dir: Path | None = None) -> Path:
    return (base_dir or app_dir()) / DEFAULT_LOG_NAME


def setup_logging(
    *,
    level: str = "INFO",
    log_path: Path | str | None = None,
    console: bool = True,
) -> logging.Logger:
    """Nastavi root logger aplikacije (idempotentno)."""
    logger = logging.getLogger(LOGGER_NAME)
    if getattr(logger, "_kirkpr_configured", False):
        logger.setLevel(getattr(logging, level.upper(), logging.INFO))
        return logger

    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.propagate = False
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    target = Path(log_path) if log_path else default_log_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(target, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except OSError:
        pass

    if console:
        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setFormatter(formatter)
        # V GUI načinu je konzola pogosto skrita; še vedno uporabno za CLI.
        logger.addHandler(stream_handler)

    logger._kirkpr_configured = True  # type: ignore[attr-defined]
    logger.info("Beleženje zagnano → %s", target)
    return logger


def get_logger() -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    if not getattr(logger, "_kirkpr_configured", False):
        return setup_logging(console=False)
    return logger


def safe_detail(value: Any, limit: int = 400) -> str:
    """Kratko besedilo za log brez morebitnih skrivnosti."""
    text = " ".join(str(value or "").split())
    lowered = text.casefold()
    for token in ("password", "client_secret", "authorization", "bearer ", "cookie"):
        if token in lowered:
            return "[redacted]"
    if len(text) > limit:
        return text[: limit - 1] + "…"
    return text


__all__ = [
    "DEFAULT_LOG_NAME",
    "app_dir",
    "default_log_path",
    "get_logger",
    "safe_detail",
    "setup_logging",
]
