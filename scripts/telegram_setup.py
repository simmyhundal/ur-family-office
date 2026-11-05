"""Set up Telegram alerts (free). One-time, per person.

1. In Telegram, message @BotFather: /newbot, pick a name, copy the token into .env as TELEGRAM_BOT_TOKEN.
2. Each person who should get alerts opens the bot and sends it any message (e.g. /start).
3. Run:  python scripts/telegram_setup.py          -> lists who messaged the bot and the TELEGRAM_CHAT_IDS line to use
         python scripts/telegram_setup.py --test   -> sends a "UFO test" message to every id in TELEGRAM_CHAT_IDS
"""
import argparse

from ufo.config import load_settings
from ufo.treasury.notify import TelegramNotifier

ap = argparse.ArgumentParser()
ap.add_argument("--test", action="store_true", help="send a test message to the configured chats")
args = ap.parse_args()
s = load_settings()
if not s.telegram_bot_token:
    raise SystemExit("Set TELEGRAM_BOT_TOKEN in .env first (create a bot with @BotFather).")

if args.test:
    TelegramNotifier(s).send("UFO test: alerts are set up. You will see Joint-account warnings here.")
    print(f"Sent a test message to {len(s.telegram_chat_ids)} chat(s).")
else:
    n = TelegramNotifier.__new__(TelegramNotifier)
    n._token, n._chats = s.telegram_bot_token, []
    me = n._call("getMe", {})["result"]
    updates = n._call("getUpdates", {})["result"]
    people = {}
    for u in updates:
        chat = (u.get("message") or {}).get("chat") or {}
        if chat.get("type") == "private":
            people[chat["id"]] = " ".join(filter(None, [chat.get("first_name"), chat.get("last_name")])) or chat.get("username", "?")
    print(f"Bot: @{me['username']}")
    if not people:
        raise SystemExit("No one has messaged the bot yet. Open it in Telegram, send /start, and run this again.")
    for cid, name in people.items():
        print(f"  {name}: {cid}")
    print(f"\nAdd to .env:\nTELEGRAM_CHAT_IDS={','.join(str(c) for c in people)}")
