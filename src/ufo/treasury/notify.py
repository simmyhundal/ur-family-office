"""Alert delivery. Console by default (dry run); Twilio only when explicitly enabled."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Protocol

from ..config import Settings


class Notifier(Protocol):
    def send(self, message: str) -> None: ...


class ConsoleNotifier:
    def send(self, message: str) -> None:
        print(f"[dry run, not sent] {message}")


class TwilioNotifier:
    def __init__(self, settings: Settings):
        missing = [k for k in ("twilio_account_sid", "twilio_auth_token", "twilio_from_number", "alert_phone_number")
                   if not getattr(settings, k)]
        if missing:
            raise ValueError(f"Missing Twilio settings: {', '.join(missing)}")
        from twilio.rest import Client  # imported lazily so tests and dry runs don't need credentials

        self._client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
        self._from, self._to = settings.twilio_from_number, settings.alert_phone_number

    def send(self, message: str) -> None:
        self._client.messages.create(from_=self._from, to=self._to, body=message)


class TelegramNotifier:
    """Sends plain-text messages through a Telegram bot to each configured chat. Free, no carrier registration.
    Note: Telegram bot chats are not end-to-end encrypted; alerts contain balances."""

    API = "https://api.telegram.org"

    def __init__(self, settings: Settings):
        if not settings.telegram_bot_token or not settings.telegram_chat_ids:
            raise ValueError("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_IDS (run scripts/telegram_setup.py).")
        self._token, self._chats = settings.telegram_bot_token, settings.telegram_chat_ids

    def _call(self, method: str, payload: dict) -> dict:
        req = urllib.request.Request(f"{self.API}/bot{self._token}/{method}", data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            try:
                why = json.loads(e.read()).get("description", e.reason)
            except Exception:
                why = e.reason
            raise RuntimeError(f"Telegram {method} failed: {why}") from None  # never include the URL: it contains the token
        except urllib.error.URLError as e:
            raise RuntimeError(f"Telegram {method} failed: {e.reason}") from None

    def send(self, message: str) -> None:
        errors = []
        for chat in self._chats:
            try:
                self._call("sendMessage", {"chat_id": chat, "text": message, "disable_web_page_preview": True})
            except RuntimeError as e:
                errors.append(f"chat {chat}: {e}")
        if errors:
            raise RuntimeError("; ".join(errors))


class MultiNotifier:
    def __init__(self, notifiers: list[Notifier]):
        self._notifiers = notifiers

    def send(self, message: str) -> None:
        errors = []
        for n in self._notifiers:
            try:
                n.send(message)
            except Exception as e:  # keep going so one broken channel does not silence the alert
                errors.append(f"{type(n).__name__}: {e}")
        if errors:
            raise RuntimeError("; ".join(errors))


def build_notifier(settings: Settings, channel: str = "auto") -> Notifier:
    """auto: Telegram if configured, else Twilio. telegram / twilio: that one. all: every configured channel."""
    has_tg = bool(settings.telegram_bot_token and settings.telegram_chat_ids)
    has_sms = all(getattr(settings, k) for k in ("twilio_account_sid", "twilio_auth_token", "twilio_from_number", "alert_phone_number"))
    if channel == "telegram" or (channel == "auto" and has_tg):
        return TelegramNotifier(settings)
    if channel == "twilio" or (channel == "auto" and has_sms):
        return TwilioNotifier(settings)
    if channel == "all":
        chosen = ([TelegramNotifier(settings)] if has_tg else []) + ([TwilioNotifier(settings)] if has_sms else [])
        if chosen:
            return MultiNotifier(chosen)
    raise ValueError("No alert channel is configured. Set up Telegram (scripts/telegram_setup.py) or Twilio in .env.")
