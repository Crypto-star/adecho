"""Centralized logging: all output goes to `logs/api.log`. Terminal stays quiet.

Call `configure_logging()` as early as possible (uvicorn entrypoint).
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from loguru import logger


LOG_DIR = Path(__file__).resolve().parents[1] / "logs"
LOG_FILE = LOG_DIR / "api.log"


def _use_stdout() -> bool:
    """Railway / Fly / Docker logs are typically captured from stdout.
    Set LOG_TO_STDOUT=1 in those environments."""
    return (os.environ.get("LOG_TO_STDOUT") == "1"
            or bool(os.environ.get("RAILWAY_ENVIRONMENT"))
            or bool(os.environ.get("FLY_APP_NAME")))


class _InterceptHandler(logging.Handler):
    """Forward stdlib logging records (uvicorn, supabase, httpx…) into loguru."""

    def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        depth, frame = 2, logging.currentframe()
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def configure_logging(level: str = "INFO") -> Path:
    logger.remove()
    fmt = "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <7} | {name}:{line} | {message}"

    if _use_stdout():
        # Production / Railway: stream to stdout so the platform captures logs.
        logger.add(sys.stdout, level=level, format=fmt, backtrace=False, diagnose=False)
    else:
        # Local dev: rotating file sink so the terminal stays quiet.
        LOG_DIR.mkdir(exist_ok=True)
        logger.add(
            LOG_FILE, level=level,
            rotation="5 MB", retention=5, enqueue=True,
            backtrace=False, diagnose=False, format=fmt,
        )

    # Stdlib root → intercept into loguru.
    logging.basicConfig(handlers=[_InterceptHandler()], level=level, force=True)

    # Uvicorn's three named loggers and friends.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access",
                 "fastapi", "httpx", "httpcore", "supabase", "postgrest", "hpack"):
        lg = logging.getLogger(name)
        lg.handlers = [_InterceptHandler()]
        lg.propagate = False

    # Silence noisy INFO streams so pipeline events stand out.
    for name in ("httpx", "httpcore", "hpack", "supabase", "postgrest",
                 "uvicorn.access"):
        logging.getLogger(name).setLevel(logging.WARNING)

    # Belt-and-suspenders: swallow anything left trying to print to stdout/stderr.
    return LOG_FILE


def tail_instructions() -> str:
    return f"tail -f {LOG_FILE}"
