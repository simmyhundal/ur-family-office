"""Cron entry point for the low-balance alert.

  python jobs/check_balance.py                    # dry run: prints what would be sent
  python jobs/check_balance.py --send             # sends via Telegram (or Twilio) when low (once per day per situation)
  python jobs/check_balance.py --joint 1850.20 --personal 4200   # skip Plaid and test with made-up balances
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
from ufo.providers.plaid_client import get_balances, get_recurring_outflows
from ufo.providers.token_store import load_items
from ufo.treasury.bills import load_config
from ufo.treasury.detect import merge_bills, streams_to_bills
from ufo.treasury.low_balance import check_balance
from ufo.treasury.notify import ConsoleNotifier, build_notifier

DATA = Path(".data")
STATE = DATA / "alert_state.json"
LOG = DATA / "alerts_log.csv"


def _fingerprint(res) -> str:
    return hashlib.sha1(json.dumps([res.status, res.shortfall, res.transfer_amount, [(n, a, str(d)) for n, a, d in res.bills]]).encode()).hexdigest()


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
            w.writerow(["timestamp", "joint", "personal", "bills_total", "projected", "cushion", "status", "transfer", "personal_covers", "sent", "partner_asked"])
        # partner_asked is filled in by hand during the trial: did your partner have to ask if the bills were covered?
        w.writerow([now.isoformat(timespec="seconds"), res.joint_balance, res.personal_balance, res.bills_total, res.projected,
                    res.cushion, res.status, res.transfer_amount, res.personal_covers, sent, ""])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(DATA / "alert.json"))
    ap.add_argument("--send", action="store_true", help="actually send the alert (default: dry run)")
    ap.add_argument("--channel", choices=["auto", "telegram", "twilio", "all"], default="auto", help="auto = Telegram if configured, else Twilio")
    ap.add_argument("--joint", type=float, help="use this Joint balance instead of asking Plaid (needs --personal)")
    ap.add_argument("--personal", type=float, help="use this Personal balance instead of asking Plaid (needs --joint)")
    args = ap.parse_args(argv)

    settings = load_settings()
    cfg = load_config(args.config)
    if (args.joint is None) != (args.personal is None):
        ap.error("--joint and --personal go together")
    if args.joint is not None:
        joint, personal = args.joint, args.personal
    else:
        b = get_balances(settings, load_items(), [cfg.joint_mask, cfg.personal_mask])
        joint, personal = b[cfg.joint_mask][1], b[cfg.personal_mask][1]
    now = datetime.now()
    note = ""
    if cfg.detect_bills and args.joint is None:
        try:
            streams = get_recurring_outflows(settings, load_items(), cfg.joint_mask)
            detected, skipped = streams_to_bills(streams, now.date(), cfg.include_early_detection, cfg.ignore_streams)
            cfg.bills, dropped = merge_bills(cfg.bills, detected)
            for line in dropped + skipped:
                print(f"  bill detection: {line}")
        except RuntimeError as e:  # never silently under-warn: fall back to manual bills and say so
            print(f"Bill detection unavailable: {e}", file=sys.stderr)
            note = " (Bill detection was unavailable, so only your manual bills are counted.)"
    res = check_balance(joint, personal, cfg, now.date())
    res.message += note
    print(res.message)

    sent = False
    if res.status != "ok":
        if _already_sent(res, now.date()):
            print("Already alerted for this situation today; not sending again.")
        else:
            notifier = build_notifier(settings, args.channel) if args.send else ConsoleNotifier()
            notifier.send(res.message)
            sent = args.send
            if sent:
                DATA.mkdir(exist_ok=True)
                STATE.write_text(json.dumps({"date": str(now.date()), "fingerprint": _fingerprint(res)}))
    _log(now, res, sent)
    return 0


if __name__ == "__main__":
    sys.exit(main())
