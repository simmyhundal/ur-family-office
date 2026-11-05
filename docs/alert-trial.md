# One-week alert trial
The number that matters most: **how often your partner has to ask whether the bills are covered. The goal is zero.**
It is measured automatically: `python scripts/partner_asks.py --launch YYYY-MM-DD --review` (see the README). Log asks that happen outside Messages with `--add`.

Mark each alert: **useful** (followed by a transfer before Joint would have gone too low) or **noise** (Joint would have been fine).
Also log **missed warnings** (Joint went low with no alert), **time to act** (alert to transfer), and whether the suggested transfer amount was right.
`.data/alerts_log.csv` records every check; `partner_asks.py --fill-log` fills its `partner_asked` column.

| Date | Alert sent? | Suggested transfer | Useful / Noise / Missed | Time to act | Partner had to ask? |
|---|---|---|---|---|---|
