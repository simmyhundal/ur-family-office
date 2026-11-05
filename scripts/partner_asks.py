"""Count how often your partner asked whether the Joint account can cover things: the trial's key number, automated.

  python scripts/partner_asks.py                  # baseline (before launch) vs trial, per week
  python scripts/partner_asks.py --review         # also print the matched messages here (never stored) to spot-check the matcher
  python scripts/partner_asks.py --fill-log       # write per-day counts into .data/alerts_log.csv's partner_asked column

Config: .data/partner.json (see docs/partner.example.json). Needs Full Disk Access for the terminal running it.
Only per-day counts are saved (.data/partner_asks.csv); message text is never written to disk.
"""
import argparse
import csv
import json
from datetime import date, datetime, timedelta
from pathlib import Path

from ufo.partner.asks import count_by_day, is_cash_ask
from ufo.partner.imessage import PartnerConfig, read_partner_messages

ap = argparse.ArgumentParser()
ap.add_argument("--config", default=".data/partner.json")
ap.add_argument("--launch", help="date the alert went live (YYYY-MM-DD); default: today, so everything is baseline")
ap.add_argument("--baseline-days", type=int, default=180)
ap.add_argument("--review", action="store_true")
ap.add_argument("--fill-log", action="store_true")
args = ap.parse_args()

cfg = PartnerConfig.model_validate(json.loads(Path(args.config).read_text()))
launch = date.fromisoformat(args.launch) if args.launch else date.today()
since = datetime.combine(launch - timedelta(days=args.baseline_days), datetime.min.time())
msgs = read_partner_messages(cfg, since)
per_day = count_by_day(msgs)

before = {d: n for d, n in per_day.items() if d < launch}
after = {d: n for d, n in per_day.items() if d >= launch}
print(f"Messages from your partner scanned: {len(msgs)} (since {since:%Y-%m-%d})")
print(f"Baseline ({args.baseline_days} days before {launch}): {sum(before.values())} asks on {len(before)} day(s)")
print(f"Since launch ({launch}): {sum(after.values())} asks on {len(after)} day(s)")
if args.review:
    print("\nMatched messages (shown here only, not stored):")
    for when, text in msgs:
        if is_cash_ask(text):
            print(f"  {when:%Y-%m-%d} {text[:160]!r}")

out = Path(".data/partner_asks.csv")
out.parent.mkdir(exist_ok=True)
with out.open("w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["date", "asks"])
    w.writerows((d.isoformat(), n) for d, n in per_day.items())
print(f"\nSaved per-day counts to {out}")

if args.fill_log:
    log = Path(".data/alerts_log.csv")
    if not log.exists():
        raise SystemExit("No .data/alerts_log.csv yet; run the alert job first.")
    rows = list(csv.reader(log.open()))
    col = rows[0].index("partner_asked")
    for r in rows[1:]:
        r[col] = str(per_day.get(date.fromisoformat(r[0][:10]), 0))
    csv.writer(log.open("w", newline="")).writerows(rows)
    print(f"Filled partner_asked for {len(rows) - 1} logged check(s) in {log}")
