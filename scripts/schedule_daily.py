"""Run the alert automatically every day (macOS launch agent).

  python scripts/schedule_daily.py                 # every day at 08:00
  python scripts/schedule_daily.py --time 7:30
  python scripts/schedule_daily.py --status | --run-now | --uninstall
The job only sends a message when Joint would dip below your cushion; otherwise it just logs. Log: .data/daily.log
"""
import argparse
from pathlib import Path

from ufo.setup import schedule

ap = argparse.ArgumentParser()
ap.add_argument("--time", default="08:00", help="time of day, 24h, e.g. 08:00 or 7:30")
ap.add_argument("--status", action="store_true")
ap.add_argument("--run-now", action="store_true", help="start the scheduled job right now (a real run: it sends only if Joint is low)")
ap.add_argument("--uninstall", action="store_true")
args = ap.parse_args()

if args.status:
    print(schedule.status())
elif args.uninstall:
    print("\n".join(schedule.uninstall()))
elif args.run_now:
    schedule.run_now()
    print("Started. See .data/daily.log in a few seconds.")
else:
    hour, minute = schedule.parse_time(args.time)
    print("\n".join(schedule.install(Path.cwd(), hour, minute)))
