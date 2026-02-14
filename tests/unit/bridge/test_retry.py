"""Tests for bridge client retry logic."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from wiz.bridge.client import BridgeClient, _retry


class TestRetry:
    def test_succeeds_first_try(self):
        fn = MagicMock(return_value="ok")
        assert _retry(fn, max_retries=3) == "ok"
        assert fn.call_count == 1

    def test_retries_on_connection_error(self):
        fn = MagicMock(
            side_effect=[
                requests.ConnectionError("down"),
                "ok",
            ]
        )
        with patch("wiz.bridge.client.time.sleep"):
            result = _retry(fn, max_retries=3, backoff=0.01)
        assert result == "ok"
        assert fn.call_count == 2

    def test_exhausts_retries(self):
        fn = MagicMock(
            side_effect=requests.ConnectionError("down"),
        )
        with pytest.raises(requests.ConnectionError):
            with patch("wiz.bridge.client.time.sleep"):
                _retry(fn, max_retries=2, backoff=0.01)
        assert fn.call_count == 2

    def test_non_retryable_raises_immediately(self):
        fn = MagicMock(side_effect=ValueError("bad"))
        with pytest.raises(ValueError):
            _retry(fn, max_retries=3)
        assert fn.call_count == 1


class TestBridgeClientRetry:
    @patch("wiz.bridge.client.requests.get")
    @patch("wiz.bridge.client.time.sleep")
    def test_health_check_retries(self, mock_sleep, mock_get):
        mock_get.side_effect = [
            requests.ConnectionError("down"),
            MagicMock(status_code=200),
        ]
        client = BridgeClient(max_retries=3)
        assert client.health_check() is True

    @patch("wiz.bridge.client.requests.get")
    @patch("wiz.bridge.client.time.sleep")
    def test_health_check_all_fail(self, mock_sleep, mock_get):
        mock_get.side_effect = requests.ConnectionError("down")
        client = BridgeClient(max_retries=2)
        assert client.health_check() is False
