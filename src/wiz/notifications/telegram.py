"""Telegram notifications via direct HTTP API."""

from __future__ import annotations

import requests

from wiz.config.schema import TelegramConfig


class TelegramNotifier:
    """Send notifications via Telegram Bot API."""

    def __init__(self, bot_token: str, chat_id: str, enabled: bool = True) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.enabled = enabled
        self._base_url = f"https://api.telegram.org/bot{bot_token}"

    @classmethod
    def from_config(cls, config: TelegramConfig) -> TelegramNotifier:
        """Create from TelegramConfig. Returns disabled instance if keys are missing."""
        if not config.enabled or not config.bot_token or not config.chat_id:
            return cls(bot_token="", chat_id="", enabled=False)
        return cls(
            bot_token=config.bot_token,
            chat_id=config.chat_id,
            enabled=True,
        )

    def send_message(self, text: str, parse_mode: str = "Markdown") -> bool:
        """Send a message. Returns True on success or if disabled."""
        if not self.enabled:
            return True
        try:
            resp = requests.post(
                f"{self._base_url}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": parse_mode,
                },
                timeout=10,
            )
            return resp.status_code == 200
        except requests.RequestException:
            return False

    def notify_escalation(self, repo: str, issue: str, reason: str) -> bool:
        """Notify about an escalated issue."""
        text = (
            f"*Escalation* - {repo}\n"
            f"Issue: {issue}\n"
            f"Reason: {reason}\n"
            f"Action required: manual review"
        )
        return self.send_message(text)

    def notify_cycle_complete(self, summary: str) -> bool:
        """Notify that a cycle completed."""
        return self.send_message(f"*Cycle Complete*\n{summary}")

    def notify_error(self, error: str) -> bool:
        """Notify about an error."""
        return self.send_message(f"*Error*\n{error}")
