"""Tests for logging configuration."""

import json
import logging

from wiz.logging_config import JsonFormatter, setup_logging


class TestJsonFormatter:
    def test_format_produces_json(self):
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="wiz.test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="hello %s",
            args=("world",),
            exc_info=None,
        )
        output = formatter.format(record)
        data = json.loads(output)
        assert data["level"] == "INFO"
        assert data["logger"] == "wiz.test"
        assert data["message"] == "hello world"

    def test_format_with_exception(self):
        formatter = JsonFormatter()
        try:
            raise ValueError("boom")
        except ValueError:
            import sys
            record = logging.LogRecord(
                name="wiz.test",
                level=logging.ERROR,
                pathname="test.py",
                lineno=1,
                msg="failed",
                args=(),
                exc_info=sys.exc_info(),
            )
        output = formatter.format(record)
        data = json.loads(output)
        assert "exception" in data
        assert "ValueError" in data["exception"]


class TestSetupLogging:
    def test_setup_default(self):
        setup_logging(level="DEBUG")
        logger = logging.getLogger("wiz")
        assert logger.level == logging.DEBUG
        # Cleanup
        logger.handlers.clear()

    def test_setup_json(self):
        setup_logging(level="INFO", json_output=True)
        logger = logging.getLogger("wiz")
        assert any(
            isinstance(h.formatter, JsonFormatter)
            for h in logger.handlers
        )
        # Cleanup
        logger.handlers.clear()

    def test_no_duplicate_handlers(self):
        logger = logging.getLogger("wiz")
        logger.handlers.clear()
        setup_logging(level="INFO")
        setup_logging(level="INFO")
        setup_logging(level="INFO")
        assert len(logger.handlers) == 1
        # Cleanup
        logger.handlers.clear()
