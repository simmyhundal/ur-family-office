"""Review what Plaid detected as recurring bills on the Joint account, and how they merge with your manual bills.
Read-only. Run before trusting `detect_bills` in the alert config.

  python scripts/show_detected_bills.py [--config .data/alert.json]
"""
import argparse
from datetime import date

from ufo.config import load_settings
from ufo.providers.plaid_client import get_recurring_outflows
from ufo.providers.token_store import load_items
from ufo.treasury.bills import bills_due, load_config
from ufo.treasury.detect import merge_bills, streams_to_bills

ap = argparse.ArgumentParser()
ap.add_argument("--config", default=".data/alert.json")
args = ap.parse_args()

cfg, today = load_config(args.config), date.today()
streams = get_recurring_outflows(load_settings(), load_items(), cfg.joint_mask)
detected, skipped = streams_to_bills(streams, today, cfg.include_early_detection, cfg.ignore_streams)
merged, dropped = merge_bills(cfg.bills, detected)

print(f"\nDetected {len(detected)} bills from {len(streams)} recurring streams:")
for b in sorted(detected, key=lambda b: b.due):
    print(f"  {b.name:<32} ${b.amount:>9,.2f}  next {b.due}  {b.repeat}")
print("\nSkipped:" if skipped else "\nNothing skipped.")
for line in skipped:
    print("  -", line)
if dropped:
    print("\nDropped because you already entered them by hand:")
    for line in dropped:
        print("  -", line)
print(f"\nWhat the alert would count before {cfg.next_topup}:")
for n, a, d in bills_due(merged, today, cfg.next_topup):
    print(f"  {d}  {n:<32} ${a:>9,.2f}")
