# ur-family-office (UFO: "Ur Family Office")

A small tool for one household (two people, a Joint and a Personal Chase account) that **warns before the Joint account runs low and says what to do**, so the partner never has to ask "do we have enough for the card?". Python 3.12, private repo, read-only: **it never moves money**. Built for the owner first; every feature has to earn its place.

Update the "Current state" section at the end of every session.

## Current state (2026-11-05, end of session)
**Live on the owner's Mac mini:** Plaid is linked to Chase (production; one healthy connection with two checking accounts and two cards; read-only products). A Telegram bot posts to a private group (so far the owner only). A launchd agent (`com.ufo.daily-check`) runs `python -m jobs.check_balance --send` **every Monday 08:00**. Config is `.data/alert.json` (gitignored): cushion and Personal minimum $1,500, rent not paid from Joint ($0), two monthly deposits from Personal dated the 1st, one card paid from Joint. **The first on-demand status message ("Joint is covered through Nov 30") was sent to Telegram on 2026-11-05.** **Also verified live on 2026-11-05 (owner confirmed in the group): the on-demand "covered" message and a real low-balance alert (test run with `--joint 1000 --personal 5000 --send`, minimal wording, no figures). The weekly "covered" heartbeat (`notify_when_ok`) is now enabled in `.data/alert.json`; detail stays minimal.**

**What the check models:** today's Joint balance, walked day by day through the window: card payments out (statement balance and due date from Plaid Liabilities; looked at up to 30 days early), manual bills out, scheduled deposits in (same-day bills first). It compares the *lowest point* to the cushion and says how much to move from Personal (shortfall rounded up to $10, Personal keeps its minimum).

**Not yet verified live:** the first scheduled Monday run; the partner in the group (issue 20: send her `docs/safety-for-partner.md`, warn her the test alert was a drill, then add her); the "headroom" level; the heartbeat arriving on a scheduled Monday; Twilio (unused). **Not modeled:** any outflow other than cards and manual bills (see the M2 milestone).

Tests: `.venv/bin/python -m pytest -q` (247). Lint for undefined names: `.venv/bin/ruff check --select F src jobs scripts tests`.

## Run it
- Setup wizard (Plaid, accounts, rent/deposits, Telegram, schedule): `python -m ufo.setup`
- Check now (dry run, prints the full local message and what would be sent): `python -m jobs.check_balance`
- Look ahead to a date, or send a status message on demand even when all is well: `--through eom|YYYY-MM-DD`, `--report`, `--send`
- What will the alert count? `python scripts/show_detected_bills.py`
- Schedule: `python scripts/schedule_daily.py [--weekday mon|daily] [--time 8:00] [--status|--run-now|--uninstall]`; output in `.data/daily.log`
- Telegram helpers: `python scripts/telegram_setup.py [--test|--harden]`
- Partner-ask metric (reads the owner's Messages): `python scripts/partner_asks.py --review|--near-misses|--discover|--add DATE`
- Venv is `.venv` (Homebrew python@3.12). There is no `timeout` command on macOS; use `perl -e 'alarm(90); exec @ARGV' ...`. The shell is zsh (unquoted variables do not word-split).

## Backlog (GitHub milestones)
- **M1: Live and trusted:** [add the partner to the group + share the safety page](https://github.com/simmyhundal/ur-family-office/issues/20), [verify the first scheduled run and a real low-balance alert](https://github.com/simmyhundal/ur-family-office/issues/21)
- **M2: Numbers you can trust, privately:** [model other outflows](https://github.com/simmyhundal/ur-family-office/issues/22), [private "Joint is covered" dashboard (exact numbers)](https://github.com/simmyhundal/ur-family-office/issues/8), [detect the regular deposit from Plaid](https://github.com/simmyhundal/ur-family-office/issues/14), [partner-ask counter recall](https://github.com/simmyhundal/ur-family-office/issues/15)
- **M3: Portfolio tools (later):** [tax-aware sells](https://github.com/simmyhundal/ur-family-office/issues/1), [live prices](https://github.com/simmyhundal/ur-family-office/issues/2), [order tickets](https://github.com/simmyhundal/ur-family-office/issues/3)
- Next best step after M1: measure the blind spot in [issue 22](https://github.com/simmyhundal/ur-family-office/issues/22) using `.data/alerts_log.csv`.

## How the owner likes to work (carry these across sessions)
- Smaller steps; one terminal wizard before any other front end. Domestic (US, USD) only; ignore foreign-currency and international cases.
- **Give GitHub issues and PRs as full clickable links** with a few words on what they are, never bare `#12`.
- Squash-merge PRs (one clean commit on `main`; keeps stray commits out of history). Ask before outward actions beyond what was requested.
- The first live runs each exposed a bug the unit tests missed; run things for real early, then add a test for what broke.

## Safety rules (do not relax without asking)
- **Read-only.** Never add code that moves money or submits orders. Fidelity has no trading API; any execution needs its own design, approvals and a broker partner.
- **Secrets never go in the repo:** Plaid tokens, Telegram bot token, Twilio keys, account numbers, CSV exports. `.env`, `.data/`, `*.csv` are gitignored. Never put a token in an error message or log.
- **Remote channels (Telegram, SMS) are not end-to-end encrypted.** They get only `CheckResult.public_message` (minimal: no figures) or, for a chat explicitly opted in via `telegram_detail`, `headroom_message` (the cushion and the lowest balance rounded down to $500). Exact balances, bill amounts, bill names, account digits and the transfer amount are never sent; a `full` level is rejected by the config. The full message stays local (printed, and `.data/last_alert.txt`, mode 0600).
- **The alert bot is write-only:** `TelegramNotifier` can only call `sendMessage`, to chat IDs from `.env`. It never reads updates. Setup helpers live in `providers/telegram_admin.py` and are never on the alert path. Keep `docs/safety-for-partner.md` accurate when behavior changes.
- **Real data never goes in tests, fixtures, issues, PRs or commit messages.** Use invented values. Before committing, sweep: `git grep -n -i -E "<real figures, masks, names>"`. The partner's Messages are read-only and local: never write message text to disk, logs or the repo; `.data/partner.json` is local only. (A past mistake: real holdings and an account number were put in tests and had to be scrubbed.)
- Financial output is information, not advice; keep the disclaimer in user-facing text.

## Design decisions (details in `docs/decisions/`)
Python, lean stack; no database or server until a feature needs one (0001). Read-only v1 (0002). Telegram first, SMS later (0003). Minimal write-only remote alerts (0004). Bills: card statement balances + manual bills + scheduled deposits, check the running balance, rent $0 unless paid from Joint (0005). Per-chat detail levels, exact numbers never over a chat (0006).

## Pitfalls already hit (do not repeat)
- **Chase OAuth:** linking the same bank again creates a second Plaid connection and Chase breaks the first (`ITEM_LOGIN_REQUIRED`). The link flow prunes superseded connections; accounts are de-duplicated across connections; a broken connection is skipped, and the job prints a plain message and exits 2 instead of a traceback.
- **Plaid history length is fixed when a connection is created** (default 90 days, max 730). We request 730 and the optional `liabilities` product at link time.
- **Plaid's holdings omit the cash / money-market sweep** (fin-advisor prototype); derive it as `balances.current - sum(holdings)`.
- **Plaid SDK enums** are model objects; use `_val()`. Every Plaid-facing function is tested against a fake client, and a test lints for undefined names.
- **Telegram:** bots cannot be created via API (only in @BotFather); the owner made a *group* once and the wizard missed it, so groups (negative chat IDs) count. `getUpdates` is only for setup.
- **Wizard loops must be capped** (a missing scripted answer once hung the test run). Tests drive the wizard through a scripted `Prompter`.
- **Sandbox/classifier:** force-pushes and pushing content derived from the owner's private messages are blocked. Use normal commits and squash merges. The terminal tool can only start in the session's folder; start the session in this repo.

## Where things are
`src/ufo/treasury/` (check, bills, deposits, detection, notifiers) · `src/ufo/providers/` (Plaid, Telegram admin, token store, Fidelity CSV) · `src/ufo/setup/` (wizard, env file, schedule) · `src/ufo/partner/` (Messages reader and ask matcher) · `src/ufo/rebalance/` (ported withdrawal/rebalance engine; target weights come from the owner's Redistribution Google Sheet, read live, never hard-coded) · `jobs/check_balance.py` · `scripts/` · `docs/` (safety page, decisions, config examples) · `tests/`.
