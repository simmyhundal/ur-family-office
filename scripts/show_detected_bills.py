"""Review exactly which bills the alert would count: manual, rent (recurring detection) and credit cards (Plaid Liabilities).
Read-only. Run before trusting `detect_bills` in the alert config.

  python scripts/show_detected_bills.py [--config .data/alert.json]
"""
import argparse
from datetime import date

from ufo.config import load_settings
from ufo.providers.token_store import load_items
from ufo.treasury.bills import bills_due, load_config
from ufo.treasury.low_balance import effective_window_end
from ufo.treasury.sources import collect_bills

ap = argparse.ArgumentParser()
ap.add_argument("--config", default=".data/alert.json")
args = ap.parse_args()

cfg, today = load_config(args.config), date.today()
bills, info, failures = collect_bills(load_settings(), load_items(), cfg, today)
print("\nWhat the detectors found and decided:")
for line in info or ["(nothing to report)"]:
    print("  -", line)
for f in failures:
    print("  PROBLEM:", f)
# apply the same look-ahead the alert uses, including the early look at card payments, so this matches what it will count
cfg.bills = bills
end = effective_window_end(cfg, today)
print(f"\nBills the alert would count through {end}:")
for n, a, d in bills_due(bills, today, end):
    print(f"  {d}  {n:<36} ${a:>10,.2f}")
print("\nScheduled deposits it would count:")
for n, a, d in bills_due(cfg.scheduled_deposits, today, end) or [("(none)", 0, "")]:
    print(f"  {d}  {n:<36} ${a:>10,.2f}")
