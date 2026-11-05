"""One-time Telegram bot setup helpers (find chat ids, check and harden the bot). NOT used on the alert path:
alerts go through treasury.notify.TelegramNotifier, which can only send."""
from __future__ import annotations

import json
import urllib.error
import urllib.request

API = "https://api.telegram.org"


class TelegramAdmin:
    def __init__(self, token: str):
        self._token = token

    def _call(self, method: str, payload: dict | None = None) -> dict:
        req = urllib.request.Request(f"{API}/bot{self._token}/{method}", data=json.dumps(payload or {}).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read())["result"]
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Telegram {method} failed (HTTP {e.code})") from None  # never include the URL: it has the token
        except urllib.error.URLError as e:
            raise RuntimeError(f"Telegram {method} failed: {e.reason}") from None

    def me(self) -> dict:
        return self._call("getMe")

    def people_who_messaged(self) -> dict[int, str]:
        out: dict[int, str] = {}
        for u in self._call("getUpdates"):
            chat = (u.get("message") or {}).get("chat") or {}
            if chat.get("type") == "private":
                out[chat["id"]] = " ".join(filter(None, [chat.get("first_name"), chat.get("last_name")])) or chat.get("username", "?")
        return out

    def webhook_url(self) -> str:
        return self._call("getWebhookInfo").get("url") or ""

    def harden(self) -> list[str]:
        """Make the bot look and act send-only. Returns warnings about things only BotFather can change."""
        self._call("setMyDescription", {"description": "Send-only household alerts. This bot does not read or answer messages."})
        self._call("setMyShortDescription", {"short_description": "Send-only alerts. It does not reply."})
        self._call("setMyCommands", {"commands": []})
        warnings = []
        me = self.me()
        if me.get("can_join_groups"):
            warnings.append("Bot can be added to groups. In @BotFather: /mybots > your bot > Bot Settings > Allow Groups? > Turn off.")
        if self.webhook_url():
            warnings.append("A webhook is set on this bot; remove it so nothing can receive messages through it.")
        return warnings
