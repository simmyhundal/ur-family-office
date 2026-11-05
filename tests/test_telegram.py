import io
import json
import urllib.error

import pytest

from ufo.config import Settings
from ufo.providers.plaid_client import HISTORY_DAYS, build_link_request
from ufo.treasury import notify
from ufo.treasury.notify import ConsoleNotifier, MultiNotifier, TelegramNotifier, TwilioNotifier, build_notifier

TG = Settings(telegram_bot_token="123:SECRET", telegram_chat_ids=["111", "222"])


class FakeResp:
    def __init__(self, body):
        self._b = json.dumps(body).encode()

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_sends_plain_text_to_every_chat(monkeypatch):
    calls = []
    monkeypatch.setattr(notify.urllib.request, "urlopen", lambda req, timeout: calls.append((req.full_url, json.loads(req.data))) or FakeResp({"ok": True}))
    TelegramNotifier(TG).send("UFO: Joint is $1,500.00")
    assert [c[1]["chat_id"] for c in calls] == ["111", "222"]
    assert all(c[0].endswith("/sendMessage") and c[1]["text"] == "UFO: Joint is $1,500.00" and "parse_mode" not in c[1] for c in calls)


def test_one_bad_chat_does_not_stop_the_others_and_the_token_never_leaks(monkeypatch):
    seen = []

    def fake(req, timeout):
        chat = json.loads(req.data)["chat_id"]
        seen.append(chat)
        if chat == "111":
            raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, io.BytesIO(b'{"description": "bot was blocked by the user"}'))
        return FakeResp({"ok": True})

    monkeypatch.setattr(notify.urllib.request, "urlopen", fake)
    with pytest.raises(RuntimeError) as e:
        TelegramNotifier(TG).send("hi")
    assert seen == ["111", "222"]
    assert "bot was blocked by the user" in str(e.value) and "SECRET" not in str(e.value)


def test_network_error_message_has_no_token(monkeypatch):
    def boom(req, timeout):
        raise urllib.error.URLError("timed out")

    monkeypatch.setattr(notify.urllib.request, "urlopen", boom)
    with pytest.raises(RuntimeError) as e:
        TelegramNotifier(TG).send("hi")
    assert "timed out" in str(e.value) and "SECRET" not in str(e.value)


def test_requires_token_and_chats():
    with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN"):
        TelegramNotifier(Settings(telegram_bot_token="x"))


def test_build_notifier_prefers_telegram_and_supports_all():
    sms = dict(twilio_account_sid="a", twilio_auth_token="b", twilio_from_number="+1", alert_phone_number="+2")
    both = Settings(telegram_bot_token="t", telegram_chat_ids=["1"], **sms)
    assert isinstance(build_notifier(both), TelegramNotifier)
    assert isinstance(build_notifier(Settings(**sms), "auto"), TwilioNotifier)  # no Telegram configured: falls back to SMS
    assert isinstance(build_notifier(both, "all"), MultiNotifier)
    with pytest.raises(ValueError, match="No alert channel"):
        build_notifier(Settings())


def test_multi_notifier_keeps_going_when_one_channel_fails():
    got = []

    class Ok:
        def send(self, m):
            got.append(m)

    class Bad:
        def send(self, m):
            raise RuntimeError("down")

    with pytest.raises(RuntimeError, match="Bad: down"):
        MultiNotifier([Bad(), Ok()]).send("x")
    assert got == ["x"]


def test_link_requests_the_maximum_history_for_recurring_detection():
    assert HISTORY_DAYS == 730
    req = build_link_request()
    assert req.transactions.days_requested == 730
    assert [p.value for p in req.products] == ["transactions"]
