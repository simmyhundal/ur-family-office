"""Alert delivery. Console by default (dry run); Twilio only when explicitly enabled."""
from __future__ import annotations

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
