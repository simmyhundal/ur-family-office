"""Guided setup: asks the questions, writes .data/alert.json, and sets up the Telegram channel (token and chat ids saved to .env).

Telegram bots can only be created by chatting with @BotFather inside Telegram (there is no API for it), so the wizard walks
you through that one step and does everything after it. Secrets are read hidden, saved to .env (owner-only), and never printed.
US accounts and USD only.
"""
from __future__ import annotations

import calendar
import json
import os
import random
import shutil
import string
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable

from ..config import Settings, load_settings
from ..providers import plaid_client, telegram_admin
from ..providers.token_store import load_items
from ..treasury.bills import AlertConfig
from ..treasury.notify import TelegramNotifier
from .envfile import update_env
from .prompts import Prompter


@dataclass
class Deps:
    root: Path = field(default_factory=Path.cwd)
    today: Callable[[], date] = date.today
    sleep: Callable[[float], None] = time.sleep
    load_settings: Callable[[], Settings] = load_settings
    load_items: Callable[[], list] = load_items
    link_account: Callable[[Settings], None] = plaid_client.link_account
    list_accounts: Callable[[Settings, list], list] = plaid_client.list_accounts
    make_admin: Callable[[str], object] = telegram_admin.TelegramAdmin
    make_notifier: Callable[[Settings], object] = TelegramNotifier
    run_dry_run: Callable[[Path], None] | None = None
    poll_seconds: int = 120
    open_url: Callable[[str], None] | None = None  # opens a link in the browser / Telegram app (macOS: `open`)
    copy: Callable[[str], None] | None = None  # puts text on the clipboard (macOS: `pbcopy`)
    suffix: Callable[[], str] = lambda: "".join(random.choices(string.ascii_lowercase + string.digits, k=4))

    @property
    def env_path(self) -> Path:
        return self.root / ".env"

    @property
    def config_path(self) -> Path:
        return self.root / ".data" / "alert.json"


def next_monthly_date(day: int, today: date) -> date:
    """The next date (today included) that falls on this day of the month; clamps for short months."""
    def clamp(y: int, m: int) -> date:
        return date(y, m, min(day, calendar.monthrange(y, m)[1]))
    this = clamp(today.year, today.month)
    if this >= today:
        return this
    y, m = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
    return clamp(y, m)


def label(a: dict) -> str:
    kind = a.get("subtype") or a.get("type") or "account"
    return f"{a['name']} …{a.get('mask') or '????'} ({kind})"


def money_input(p: Prompter, key: str, text: str, default: float | None = None) -> float:
    while True:
        raw = p.ask(key, text, None if default is None else f"{default:g}").replace("$", "").replace(",", "")
        try:
            v = float(raw)
            if v >= 0:
                return v
        except ValueError:
            pass
        p.say("Please enter a dollar amount like 1500.")


# ---------------------------------------------------------------- steps


def step_plaid(p: Prompter, d: Deps) -> tuple[Settings, list[dict]]:
    p.say("\n== 1. Plaid (read-only access to your bank) ==")
    s = d.load_settings()
    if not (s.plaid_client_id and s.plaid_secret):
        p.say("Plaid keys are not set. Get them from the Plaid dashboard (Developers > Keys).")
        cid = p.ask("plaid_client_id", "Plaid client ID")
        secret = p.secret("plaid_secret", "Plaid secret")
        env = p.ask("plaid_env", "Plaid environment (production for real accounts, sandbox for fake data)", "production")
        update_env(d.env_path, {"PLAID_CLIENT_ID": cid, "PLAID_SECRET": secret, "PLAID_ENV": env})
        s = d.load_settings()
    items = d.load_items()
    if not items:
        if p.confirm("link", "No bank is linked yet. Link your Chase accounts now?"):
            d.link_account(s)
            items = d.load_items()
    accounts: list[dict] = d.list_accounts(s, items) if items else []
    return s, accounts


def is_card(a: dict) -> bool:
    return a.get("type") == "credit" or a.get("subtype") == "credit card"


def ensure_cards(p: Prompter, d: Deps, s: Settings, accounts: list[dict]) -> list[dict]:
    """The credit card paid from Joint is usually its biggest outflow, so a first run without it gives a false sense of safety."""
    if not accounts or any(is_card(a) for a in accounts):
        return accounts
    p.say("\n== Important: the credit card ==\n"
          "No credit card is linked. The card paid from your Joint account is usually its biggest bill, and Plaid gives us the exact\n"
          "statement balance and due date, so the alert can warn you weeks ahead. Without it, a first run would say \"all clear\"\n"
          "right before the card payment lands. Strongly recommended for a first run.")
    for _ in range(5):  # capped: never loop forever
        if p.confirm("link_card", "Link the card now? (In the Chase window, select the card paid from Joint.)", True):
            d.link_account(s)
            accounts = d.list_accounts(s, d.load_items())
            if any(is_card(a) for a in accounts):
                return accounts
            p.say("Still no card in the linked accounts. Make sure the card is ticked in the Chase window.")
            continue
        if p.confirm("skip_card", "Continue WITHOUT the card? The alert will under-warn until you add it.", False):
            return accounts
        # otherwise ask again
    p.say("Continuing without the card. Add it later by running this wizard again; until then the alert will under-warn.")
    return accounts


def step_accounts(p: Prompter, accounts: list[dict]) -> dict:
    p.say("\n== 2. Which accounts? ==")
    if not accounts:
        p.say("No linked accounts found, so enter the last digits by hand.")
        return {"joint_mask": p.ask("joint_mask", "Last digits of the JOINT account"),
                "personal_mask": p.ask("personal_mask", "Last digits of the PERSONAL account that tops it up"), "credit_card_masks": []}
    names = [label(a) for a in accounts]
    j = p.choose("joint", "Which is the JOINT account (the one to watch)?", names)
    rest = [i for i in range(len(accounts)) if i != j]
    pi = p.choose("personal", "Which account tops up Joint (your PERSONAL account)?", [names[i] for i in rest])
    cards = [i for i in range(len(accounts)) if is_card(accounts[i])]
    picked: list[str] = []
    if cards:
        sel = p.choose_many("cards", "Which credit cards are paid from the Joint account?", [names[i] for i in cards])
        picked = [accounts[cards[i]]["mask"] for i in sel]
    return {"joint_mask": accounts[j]["mask"], "personal_mask": accounts[rest[pi]]["mask"], "credit_card_masks": picked}


def step_flows(p: Prompter, d: Deps) -> dict:
    p.say("\n== 3. Money in and out of Joint ==")
    out: dict = {}
    out["rent_paid_from_joint"] = p.confirm("rent", "Is rent withdrawn from the Joint account? (Most people: no, it counts as $0)", False)
    out["rent_streams"] = []
    if out["rent_paid_from_joint"]:
        landlord = p.ask("landlord", "Name on the rent payment, e.g. your landlord or property manager (Enter to skip)", "")
        out["rent_streams"] = [landlord] if landlord else []
    out["scheduled_deposits"] = []
    more = p.confirm("deposit", "Is there a regular deposit into Joint (for example a transfer from your Personal account)?", True)
    while more:
        name = p.ask("deposit_name", "What is it called", "Regular deposit from Personal")
        amount = money_input(p, "deposit_amount", "Amount in dollars (if it varies, enter the low end)")
        day = int(p.ask("deposit_day", "Day of the month it arrives (1-31)", "1"))
        funded = p.confirm("deposit_from_personal", "Is it funded from your Personal account?", True)
        out["scheduled_deposits"].append({"name": name, "amount": amount, "due": next_monthly_date(min(max(day, 1), 31), d.today()).isoformat(),
                                          "repeat": "monthly", "from_personal": funded})
        more = p.confirm("deposit_more", "Any other regular deposit into Joint? (for example a loan repayment between the two of you)", False)
    out["personal_floor"] = money_input(p, "floor", "Minimum balance Personal should always keep (dollars)", 1500)
    out["cushion"] = money_input(p, "cushion", "Cushion: the lowest you want Joint to ever get (dollars)", 1000)
    out["lookahead_days"] = int(p.ask("lookahead", "How many days ahead should it look", "14"))
    return out


def write_config(p: Prompter, d: Deps, accounts: dict, flows: dict) -> None:
    cfg = {**accounts, **flows, "detect_bills": bool(accounts["credit_card_masks"] or flows["rent_paid_from_joint"]), "bills": []}
    AlertConfig.model_validate(cfg)  # fail now, not at 7am
    if d.config_path.exists():
        if not p.confirm("overwrite", f"{d.config_path.name} already exists. Replace it (a backup is kept)?", False):
            p.say("Kept your existing config; the new answers were not saved.")
            return
        shutil.copy(d.config_path, d.config_path.with_suffix(".json.bak"))
    d.config_path.parent.mkdir(parents=True, exist_ok=True)
    d.config_path.write_text(json.dumps(cfg, indent=2) + "\n")
    os.chmod(d.config_path, 0o600)
    p.say(f"Saved {d.config_path}.")


def bot_username_suggestion(d: Deps) -> str:
    return f"ufo_alerts_{d.suffix()}_bot"


def step_telegram(p: Prompter, d: Deps, s: Settings) -> None:
    p.say("\n== 4. Telegram alerts (free) ==")
    p.say("Alerts are deliberately minimal: no balances, amounts or account details leave your computer, and the bot only sends.")
    if s.telegram_bot_token and s.telegram_chat_ids:
        p.say(f"Telegram is already set up ({len(s.telegram_chat_ids)} recipient(s)).")
        if not p.confirm("telegram_redo", "Set it up again?", False):
            return
    elif not p.confirm("telegram", "Set up Telegram now?", True):
        p.say("Skipped. Run this again any time.")
        return

    admin, me, token = None, None, None
    if s.telegram_bot_token:  # a bot from an earlier run: reuse it instead of making another
        try:
            admin = d.make_admin(s.telegram_bot_token)
            me = admin.me()
            if p.confirm("tg_reuse", f"Found your bot @{me['username']} from an earlier run. Use it?", True):
                token = s.telegram_bot_token
            else:
                admin = me = None
        except RuntimeError:
            admin = me = None
    if admin is None:
        username, name = bot_username_suggestion(d), "UFO Alerts"
        p.say("\nTelegram only lets bots be created by chatting with its official @BotFather (there is no API for it), so here is the\n"
              "exact script. I am opening BotFather for you; just paste these three messages, one at a time:\n"
              f"  1.  /newbot\n  2.  {name}\n  3.  {username}      (must end in 'bot'; if it is taken, add a few letters)\n"
              "Then BotFather replies with a long token. Copy it.")
        if d.copy:
            d.copy("/newbot")
        if d.open_url:
            d.open_url("https://t.me/BotFather")
        for _ in range(3):
            token = p.secret("tg_token", "Paste the token here")
            try:
                admin = d.make_admin(token)
                me = admin.me()
                break
            except RuntimeError:
                p.say("That token did not work. Check it and try again.")
        if admin is None:
            p.say("Skipping Telegram; run the wizard again when you have the token.")
            return
        update_env(d.env_path, {"TELEGRAM_BOT_TOKEN": token})
        p.say(f"Connected to @{me['username']}. Token saved to .env.")

    p.say(f"\nNow open your new bot and press START: https://t.me/{me['username']}?start=ufo\n"
          "(Your partner does the same. A group chat with the bot in it also works: add the bot and send /start there.)")
    if d.open_url:
        d.open_url(f"https://t.me/{me['username']}?start=ufo")
    chats: dict[int, str] = {}
    waited = 0
    while True:
        chats = admin.chats_that_messaged()
        if chats or waited >= d.poll_seconds:
            break
        d.sleep(3)
        waited += 3
    for _ in range(10):  # capped: never loop forever
        if chats:
            p.say("Found: " + ", ".join(chats.values()))
            if not p.confirm("tg_more", "Is anyone else still to message the bot?", False):
                break
        elif not p.confirm("tg_retry", "Nothing yet. Press START in the bot's chat, then check again?", True):
            break
        chats = admin.chats_that_messaged()
    if not chats:
        p.say("No chats yet, so alerts are not enabled. Run the wizard again after messaging the bot.")
        return
    ids = list(chats)
    if len(ids) > 1:
        keep = p.choose_many("tg_who", "Who should receive alerts? (Enter for everyone)", [chats[i] for i in ids]) or list(range(len(ids)))
        ids = [ids[i] for i in keep]
    update_env(d.env_path, {"TELEGRAM_CHAT_IDS": ",".join(str(i) for i in ids)})
    p.say(f"Saved {len(ids)} recipient(s) to .env.")
    warnings = admin.harden(uses_group=any(i < 0 for i in ids))
    p.say("Bot set to send-only." if not warnings else "Bot set to send-only. Two things only BotFather can change:")
    for w in warnings:
        p.say(f"  - {w}")
    if p.confirm("tg_test", "Send a test message now?", True):
        d.make_notifier(d.load_settings()).send("UFO test: alerts are set up. You will see Joint-account warnings here (no amounts or balances).")
        p.say("Sent. Check Telegram.")


def run(p: Prompter, d: Deps | None = None) -> None:
    d = d or Deps()
    p.say("UFO setup. About five minutes. Nothing here can move money; Plaid access is read-only.")
    s, accounts = step_plaid(p, d)
    accounts = ensure_cards(p, d, s, accounts)
    acct = step_accounts(p, accounts)
    flows = step_flows(p, d)
    write_config(p, d, acct, flows)
    step_telegram(p, d, s)
    p.say("\n== Done ==")
    p.say("Check what the alert will count:   python scripts/show_detected_bills.py\nTry it (nothing is sent):         python -m jobs.check_balance\nSend for real:                    python -m jobs.check_balance --send")
    if d.run_dry_run and p.confirm("dry", "Run a dry check now?", True):
        d.run_dry_run(d.root)


def mac_open(url: str) -> None:
    try:
        subprocess.run(["open", url], check=False, timeout=10)
    except Exception:  # not macOS, or no handler: the link is printed anyway
        pass


def mac_copy(text: str) -> None:
    try:
        subprocess.run(["pbcopy"], input=text.encode(), check=False, timeout=10)
    except Exception:
        pass


def default_dry_run(root: Path) -> None:
    subprocess.run([sys.executable, "-m", "jobs.check_balance"], cwd=root, check=False)
