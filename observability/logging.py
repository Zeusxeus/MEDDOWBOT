from __future__ import annotations

import logging
import sys
from typing import Any

import structlog
from config.settings import settings


def setup_logging() -> None:
    """
    Configure structlog for the application.
    Uses JSON formatting in production and colored console output in development.
    """
    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.format_exc_info,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if settings.env == "prod" or settings.obs.log_format == "json":
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=True))

    structlog.configure(
        processors=processors,
        logger_factory=structlog.PrintLoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(settings.obs.log_level.upper())
        ),
        cache_logger_on_first_use=True,
    )

    # Basic configuration for standard library logs (like from libraries)
    # This won't format them through structlog but will set the correct level and stream
    logging.basicConfig(
        level=logging.getLevelName(settings.obs.log_level.upper()),
        format="%(message)s",
        stream=sys.stdout,
    )
