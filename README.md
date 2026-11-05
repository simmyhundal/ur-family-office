# UFO: Your Family Office

UFO warns you before your checking account runs low, and grows into a full family office for everyday households.
It is being built for one household first; each feature has to earn its place.

## Status
| Area | State |
|---|---|
| Low-balance alert (v1): balance minus bills due soon vs a cushion, text when below | built; needs a Chase link and the one-week trial |
| Withdrawal rebalancer: proposed trades (sell/buy/full/auto modes), per-account withdrawals, Fidelity CSV input | ported from the `fin-advisor` prototype; output matches it exactly (22 tests) |
| Order tickets | planned (issue #3) |
| Bill detection from Plaid recurring transactions | planned |
| Tax-lot optimization (HIFO, TLH) | planned; needs per-lot data Plaid does not provide |
| Multi-generational access (roles, delegation) | planned |

v1 is read-only: it cannot move money. UFO gives information and alerts, not financial, tax or legal advice.

## Layout
- `src/ufo/providers/` data in (Plaid, Fidelity CSV, quotes); read-only
- `src/ufo/treasury/` low-balance alert, bills, notifications
- `src/ufo/rebalance/` withdrawal planning and order tickets
- `src/ufo/tax/`, `access/`, `api/`, `store/` later phases
- `jobs/` cron entry points; `scripts/` one-offs (e.g. Plaid link)
- `docs/decisions/` short decision records

## Setup
Needs Python 3.11+.

```bash
python3.11 -m venv .venv && source .venv/bin/activate   # or: uv venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
pytest
```

## Low-balance alert (v1)
Read-only. Pulls your checking balance through Plaid, subtracts the bills you entered that fall due before your next top-up, and texts you when what is left is under your cushion.

1. `cp .env.example .env` and fill `PLAID_CLIENT_ID`, `PLAID_SECRET`, `PLAID_ENV` (real Chase balances need Plaid production access), and the `TWILIO_*` / `ALERT_PHONE_NUMBER` values.
2. `python scripts/link_account.py` and connect your checking account (the token is stored in `.data/items.json`, gitignored).
3. Copy `docs/alert.example.json` to `.data/alert.json` and set `cushion`, `next_topup` (next paycheck or planned transfer in), and your `bills` (`"repeat": "monthly"` for rent).
4. Try it: `python -m jobs.check_balance --balance 1500` (no Plaid, dry run), then `python -m jobs.check_balance` (live balance, still dry run), then `--send` to text.
5. Schedule `--send` daily (cron / launchd). It texts at most once per day per situation, warns if `next_topup` has passed, and logs every check to `.data/alerts_log.csv` for the one-week trial in `docs/alert-trial.md`.
