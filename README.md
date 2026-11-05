# UFO: Ur Family Office

UFO warns your household before the joint account runs low, tells you exactly how much to move, and grows into a full family office for everyday households.
It is being built for one household first (two people, a Joint and a Personal account at Chase); each feature has to earn its place.

## Status
| Area | State |
|---|---|
| Low-balance alert: Joint balance walked through upcoming card payments, bills and scheduled deposits vs a cushion; local detail plus a minimal Telegram message | **live** (weekly, Monday 8 AM); first status message sent 2026-11-05 |
| Setup wizard (Plaid, accounts, rent/deposits, Telegram, schedule) | built and used |
| Partner in the Telegram group, minimal or "headroom" detail, weekly "covered" message | built; partner not added yet ([milestone M1](https://github.com/simmyhundal/ur-family-office/milestone/1)) |
| Private dashboard with exact numbers, other-outflow modeling, deposit detection | planned ([milestone M2](https://github.com/simmyhundal/ur-family-office/milestone/2)) |
| Withdrawal rebalancer, Fidelity CSV input, order tickets, tax-aware sells, live prices | ported from the `fin-advisor` prototype; the rest planned ([milestone M3](https://github.com/simmyhundal/ur-family-office/milestone/3)) |
| Multi-generational access (roles, delegation) | planned |

Working on this repo? Read `CLAUDE.md` first: current state, commands, safety rules, backlog and pitfalls.

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
Read-only. Watches the **Joint** account and texts you before it would dip below your cushion, then tells you (locally) exactly how much to move from **Personal**.

**How a check works.** Starting from today's Joint balance, it walks day by day through the look-ahead window (14 days by default, or until `next_topup`): bills go out, scheduled deposits come in, and it tracks the **lowest point** the balance reaches. A card payment that lands before your regular deposit is a real dip even if the end balance looks fine. If the lowest point is under the cushion, you get an alert. The amount to move is the shortfall rounded up to the next $10, and Personal keeps a minimum ($1,500 by default) after also funding any scheduled deposit it pays for. If Personal cannot cover it, you are told how much it can send and how much is left uncovered.

**What counts as outflow (v1):**
- **Rent: $0 by default.** Many households pay rent from elsewhere. Set `"rent_paid_from_joint": true` only if rent comes out of Joint (then it is detected from recurring transactions; put your landlord's name in `rent_streams` if it is paid by Zelle).
- **Credit cards:** the statement balance and due date from Plaid Liabilities for the cards in `credit_card_masks` (the cards paid from Joint). `credit_card_amount: "minimum"` counts only the minimum payment. This is the most important input for a first run: **without a linked card the alert cannot see the biggest bill and will say "all clear" right before the payment lands**, so the wizard strongly pushes you to link it. Card payments due within 30 days are always looked at, even past the look-ahead window, so a shortfall is flagged while there is still time.
- **Manual bills** always work and win when they describe the same bill as a detected one.
- Other recurring spend (subscriptions, utilities, ...) is a later stage; `include_other_recurring` opts in early.

**What counts as inflow:** `scheduled_deposits` (as many as you need), for example a regular transfer from Personal that matches the rent your partner pays, plus a loan repayment between the two of you. If the amount varies, enter the low end.

**What leaves your machine (Telegram / SMS).** Remote channels are not end-to-end encrypted, so they only ever get a minimal message with **no balances, amounts, bill names or account details**:

> UFO: Joint may run short before Nov 07. Please check your bank app.

The full breakdown and the amount to move are printed when you run the job and saved to `.data/last_alert.txt` (owner-only). The Telegram bot is **write-only**: the alert code can only call `sendMessage`, never reads incoming messages and cannot answer questions. Run `python scripts/telegram_setup.py --harden` once to give the bot a send-only description, remove its commands and check it cannot join groups or have a webhook. (Telegram cannot stop people messaging a bot; nothing happens when they do, because nothing listens.)

### Setup
The easy way: **`python -m ufo.setup`**. It walks through everything below in about five minutes: Plaid keys and linking, picking your Joint and Personal accounts and the cards paid from Joint, the rent question, a regular deposit into Joint, your minimums, and the Telegram channel (the token and chat ids are saved to `.env`, owner-only, never printed). It validates the config before saving and keeps a backup of any existing one.

Telegram bots can only be created by chatting with @BotFather inside Telegram (there is no API for it), so that one step is yours, but the wizard makes it easy: it opens BotFather, puts `/newbot` on your clipboard, and prints the three messages to paste (a name and a username). After you paste the token, it verifies it, opens your new bot so you only press START, finds the chat ids (a direct chat or a group the bot is in both work), makes the bot send-only, and sends a test message. A bot from an earlier run is reused.

By hand, if you prefer:
1. `cp .env.example .env`, fill `PLAID_CLIENT_ID`, `PLAID_SECRET`, `PLAID_ENV` (real Chase data needs Plaid production access).
2. `python scripts/link_account.py` and connect your Chase accounts. This asks for the maximum 730 days of history (Plaid fixes the window when an account is first linked; the default is 90 days and re-linking is the only way to get more) and the optional `liabilities` product for card statement balances.
3. Telegram: create a bot with @BotFather, put its token in `TELEGRAM_BOT_TOKEN`, have everyone message the bot, then `python scripts/telegram_setup.py` prints the `TELEGRAM_CHAT_IDS` line to add; `--harden` makes the bot send-only; `--test` sends a test message. Twilio is optional.
4. Copy `docs/alert.example.json` to `.data/alert.json` and fill in `joint_mask`, `personal_mask` (last digits), `cushion`, `personal_floor`, `rent_paid_from_joint`, `credit_card_masks`, and `scheduled_deposits`.

Then:
- Review: `python scripts/show_detected_bills.py` shows exactly which bills and deposits the alert would count, and what each detector skipped and why.
- Try it: `python -m jobs.check_balance --joint 1500 --personal 4200` (no Plaid, dry run), then `python -m jobs.check_balance` (live balances, still dry run), then `--send` (`--channel telegram|twilio|all`).
- Confirm a whole month on demand: `python -m jobs.check_balance --through eom --report --send` looks ahead to the end of the month and sends a status message even when everything is fine (`--through` also takes a date).
- Schedule it: the wizard offers a scheduled run (macOS launch agent, weekly by default since the big monthly card payment is known weeks ahead), or run `python scripts/schedule_daily.py [--weekday mon|...|daily] [--time 7:30]` (`--status`, `--run-now`, `--uninstall`). Output goes to `.data/daily.log`; if the Mac is asleep at that time it runs on wake. By hand, run `python -m jobs.check_balance --send` from cron. It alerts at most once per day per situation, says so when a detector fails instead of silently under-warning, and logs every check to `.data/alerts_log.csv`.

### Telling your partner (and getting her on board)
Add your partner to the Telegram group the bot posts to. `docs/safety-for-partner.md` is a plain-English page you can send her: who can see the messages, what the bot can and cannot do, and what the realistic risks are. Each chat has a detail level (`telegram_detail` in `.data/alert.json`, or the wizard question): **minimal** (no figures) or **headroom** (the cushion and the lowest balance rounded down to $500, so she can sanity-check it against the bank app). Exact balances are never sent over Telegram. `notify_when_ok` sends a "Joint is covered" message on every check (weekly), so a quiet week is a visible all-clear, and every message says when it was checked. After your partner is in the group, turn off **Allow Groups** for the bot in @BotFather so nobody can add it elsewhere.

### Measuring the trial: how often your partner has to ask
`python scripts/partner_asks.py --launch YYYY-MM-DD --review` counts how often your partner had to ask whether Joint can cover things, from your Messages history (macOS; needs Full Disk Access for the terminal), and compares the baseline before launch with the trial. Two signals count: her asks, and your own "I paid / transferred to the joint account" messages (assumed to answer an ask; at most one per day). Only per-day counts are saved (`.data/partner_asks.csv`); message text is never stored. `--fill-log` fills the log's `partner_asked` column.
- Copy `docs/partner.example.json` to `.data/partner.json`: the chats, plus **every** number and email the partner messages from (one person often appears under several handles; `--discover` lists who sends in the configured chats, masked).
- The matcher is a keyword heuristic. `--near-misses` shows money-related messages it did not flag, so it can be tuned by eye.
- Asks that happen outside Messages (in person, calls, other apps) can be logged with `--add YYYY-MM-DD --channel in-person` and are counted too.
