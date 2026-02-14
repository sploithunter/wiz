"""Tests for Telegram notifier."""

from unittest.mock import MagicMock, patch

from wiz.config.schema import TelegramConfig
from wiz.notifications.telegram import TelegramNotifier


class TestTelegramNotifier:
    def test_send_message(self):
        with patch("wiz.notifications.telegram.requests.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=200)
            notifier = TelegramNotifier("token123", "chat456")
            assert notifier.send_message("Hello") is True

            mock_post.assert_called_once()
            call_kwargs = mock_post.call_args
            assert "sendMessage" in call_kwargs[0][0]
            assert call_kwargs[1]["json"]["text"] == "Hello"
            assert call_kwargs[1]["json"]["chat_id"] == "chat456"

    def test_disabled_mode_returns_true(self):
        notifier = TelegramNotifier("", "", enabled=False)
        assert notifier.send_message("test") is True

    def test_disabled_mode_does_not_call_api(self):
        with patch("wiz.notifications.telegram.requests.post") as mock_post:
            notifier = TelegramNotifier("", "", enabled=False)
            notifier.send_message("test")
            mock_post.assert_not_called()

    def test_from_config_enabled(self):
        config = TelegramConfig(enabled=True, bot_token="tok", chat_id="123")
        notifier = TelegramNotifier.from_config(config)
        assert notifier.enabled is True
        assert notifier.bot_token == "tok"

    def test_from_config_missing_keys_returns_disabled(self):
        config = TelegramConfig(enabled=True, bot_token="", chat_id="")
        notifier = TelegramNotifier.from_config(config)
        assert notifier.enabled is False

    def test_from_config_disabled(self):
        config = TelegramConfig(enabled=False, bot_token="tok", chat_id="123")
        notifier = TelegramNotifier.from_config(config)
        assert notifier.enabled is False

    def test_notify_escalation_format(self):
        with patch("wiz.notifications.telegram.requests.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=200)
            notifier = TelegramNotifier("tok", "123")
            notifier.notify_escalation("wiz", "#42", "3 strikes")
            text = mock_post.call_args[1]["json"]["text"]
            assert "Escalation" in text
            assert "wiz" in text
            assert "#42" in text

    def test_network_error_returns_false(self):
        import requests as req

        with patch("wiz.notifications.telegram.requests.post") as mock_post:
            mock_post.side_effect = req.ConnectionError("fail")
            notifier = TelegramNotifier("tok", "123")
            assert notifier.send_message("test") is False
