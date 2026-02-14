"""Structured logging configuration for Wiz."""

from __future__ import annotations

import json
import logging
import sys
from typing import Any


class JsonFormatter(logging.Formatter):
    """JSON log formatter for structured output."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = self.formatException(
                record.exc_info,
            )
        return json.dumps(log_entry)


def setup_logging(
    level: str = "INFO",
    json_output: bool = False,
) -> None:
    """Configure logging for Wiz.

    Args:
        level: Log level string (DEBUG, INFO, WARNING, ERROR).
        json_output: If True, use JSON formatter.
    """
    root = logging.getLogger("wiz")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    handler = logging.StreamHandler(sys.stderr)

    if json_output:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)-8s %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )

    root.addHandler(handler)
