# UFO: Ur Family Office

UFO warns your household before the joint account runs low, tells you exactly how much to move, and grows into a full family office for everyday households.
It is being built for one household first (two people, a Joint and a Personal account at Chase); each feature has to earn its place.

## Status
| Area | State |
|---|---|
| Low-balance alert (v1): Joint balance minus bills due soon vs a cushion; text with the exact amount to move from Personal | built; needs a Chase link and the one-week trial |
| Notify your partner, a "Joint is covered" dashboard, one-tap approval of the transfer | planned, after the manual alert proves useful |
| Withdrawal rebalancer: proposed trades (sell/buy/full/auto modes), per-account withdrawals, Fidelity CSV input | ported from the `fin-advisor` prototype; output matches it exactly (22 tests) |
| Order tickets | planned (issue #3) |
| Bill detection from Plaid recurring transactions | built; review with `scripts/show_detected_bills.py` before trusting it |
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
Read-only. Pulls the Joint and Personal balances through Plaid, subtracts the bills you entered that fall due before your next top-up, and texts you when Joint would end up under your cushion. The text says exactly how much to move from Personal (the shortfall rounded up to the next $10), keeping Personal above a minimum ($1,500 by default). If Personal cannot cover it, the text says how much it can send and how much is left uncovered.

The measure that matters: how often your partner has to ask whether the bills are covered. The goal is zero.

1. `cp .env.example .env` and fill `PLAID_CLIENT_ID`, `PLAID_SECRET`, `PLAID_ENV` (real Chase balances need Plaid production access), and set up Telegram alerts (free): create a bot with @BotFather, put its token in `TELEGRAM_BOT_TOKEN`, have you and your partner message the bot, then `python scripts/telegram_setup.py` prints the `TELEGRAM_CHAT_IDS` line to add (`--test` sends a test message). Twilio (`TWILIO_*`, `ALERT_PHONE_NUMBER`) is optional.
2. `python scripts/link_account.py` and connect your Chase accounts. This requests the maximum 730 days of transaction history; Plaid fixes that window when the account is first linked (default 90 days), so re-linking is the only way to get more later (the token is stored in `.data/items.json`, gitignored).
3. Copy `docs/alert.example.json` to `.data/alert.json` and set `joint_mask`, `personal_mask` (last digits), `cushion`, `personal_floor`, `next_topup` (next paycheck or planned transfer in), and your `bills` (`"repeat": "monthly"` for rent).
4. Try it: `python -m jobs.check_balance --joint 1500 --personal 4200` (no Plaid, dry run), then `python -m jobs.check_balance` (live balances, still dry run), then `--send` to send the alert (`--channel telegram|twilio|all`; default is Telegram if configured).
5. Schedule `--send` daily (cron / launchd). It alerts at most once per day per situation, warns if `next_topup` has passed, and logs every check to `.data/alerts_log.csv`; fill the `partner_asked` column by hand during the one-week trial in `docs/alert-trial.md`.

### Bill detection (optional)
Set `"detect_bills": true` in `.data/alert.json` and the alert also counts bills Plaid detects as recurring on the Joint account (rent, subscriptions, card and loan payments; transfers are excluded). Manual bills always win when both describe the same bill, and anything Plaid misses can still be entered by hand.

- Review first: `python scripts/show_detected_bills.py` lists what was detected, what was skipped and why, and exactly which bills the alert would count.
- Tuning: `ignore_streams` (names to skip), `include_early_detection` (count streams Plaid is not yet sure about).
- Amounts use the larger of the last and average charge, so variable bills err toward warning you.
- If detection is unavailable (product not ready, token missing the transactions product), the alert falls back to manual bills and says so in the text instead of silently under-warning.
- Repeat rules: weekly, biweekly, semi-monthly (approximated as every 15 days), monthly, annually.
