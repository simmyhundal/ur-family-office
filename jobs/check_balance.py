"""Cron entry point for the low-balance alert.

  python jobs/check_balance.py                    # dry run: prints what would be sent
  python jobs/check_balance.py --send             # texts via Twilio when low (once per day per situation)
  python jobs/check_balance.py --balance 1850.20  # skip Plaid and test with a made-up balance
Config: .data/alert.json (see src/ufo/treasury/bills.py). Everything it writes lives under .data/ (gitignored).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from datetime import date, datetime
from pathlib import Path

from ufo.config import load_settings
from ufo.providers.plaid_client import get_checking_balance
from ufo.providers.token_store import load_items
from ufo.treasury.bills import load_config
from ufo.treasury.low_balance import check_balance
from ufo.treasury.notify import ConsoleNotifier, TwilioNotifier

DATA = Path(".data")
STATE = DATA / "alert_state.json"
LOG = DATA / "alerts_log.csv"


def _fingerprint(res) -> str:
    return hashlib.sha1(json.dumps([res.status, res.shortfall, [(n, a, str(d)) for n, a, d in res.bills]]).encode()).hexdigest()


def _already_sent(res, today: date) -> bool:
    try:
        st = json.loads(STATE.read_text())
    except FileNotFoundError:
        return False
    return st.get("date") == str(today) and st.get("fingerprint") == _fingerprint(res)


def _log(now: datetime, res, sent: bool) -> None:
    DATA.mkdir(exist_ok=True)
    new = not LOG.exists()
    with LOG.open("a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["timestamp", "balance", "bills_total", "projected", "cushion", "status", "sent"])
        w.writerow([now.isoformat(timespec="seconds"), res.balance, res.bills_total, res.projected, res.cushion, res.status, sent])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(DATA / "alert.json"))
    ap.add_argument("--send", action="store_true", help="actually send the text (default: dry run)")
    ap.add_argument("--balance", type=float, help="use this balance instead of asking Plaid")
    args = ap.parse_args(argv)

    settings = load_settings()
    cfg = load_config(args.config)
    if args.balance is not None:
        label, balance = "manual balance", args.balance
    else:
        label, balance = get_checking_balance(settings, load_items(), cfg.account_mask)
    now = datetime.now()
    res = check_balance(balance, cfg, now.date())
    print(f"{label}: {res.message}")

    sent = False
    if res.status != "ok":
        if _already_sent(res, now.date()):
            print("Already alerted for this situation today; not sending again.")
        else:
            notifier = TwilioNotifier(settings) if args.send else ConsoleNotifier()
            notifier.send(res.message)
            sent = args.send
            if sent:
                DATA.mkdir(exist_ok=True)
                STATE.write_text(json.dumps({"date": str(now.date()), "fingerprint": _fingerprint(res)}))
    _log(now, res, sent)
    return 0


if __name__ == "__main__":
    sys.exit(main())
