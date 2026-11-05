# ur-family-office

- v1 is **read-only**. Never add code that moves money or submits orders; Phase 2 execution needs its own design, approvals and a broker partner (Fidelity has no trading API).
- Secrets (Plaid tokens, Twilio keys, account numbers, CSV exports) never go in the repo. `.env`, `.data/`, `*.csv` are gitignored; keep it that way.
- Financial output is information, not advice; keep the disclaimer in user-facing text.
- The rebalance engine is a port of the Node prototype in `~/code/fin-advisor` (`src/rebalance.mjs`, `trades.mjs`, `plan.mjs`, `csv.mjs`). Its tests are the spec: port them first, then the code. Target weights come from the user's Redistribution Google Sheet, not hard-coded values.
- Plaid's holdings omit the cash/money-market sweep; derive it as `balances.current - sum(holdings)`.
- The alert covers a Joint account (monitored) and a Personal account (funds the transfer, keeps a $1,500 minimum by default). Suggested transfers are the shortfall rounded up to the next $10. It only tells the user what to move; it never moves money.
- Alerts go through the `Notifier` interface; Telegram is the default channel (decision 0003), Twilio is optional. Never put the bot token in an error message or log.
- Plaid history length (`days_requested`) is fixed when an Item is created; keep requesting the maximum at link time.
- Remote alert channels (Telegram, SMS) are not end-to-end encrypted: send only `CheckResult.public_message` (no balances, amounts, bill names or account details). Full detail stays local. Keep the alert bot write-only (it only calls `sendMessage`; setup helpers live in `providers/telegram_admin.py`).
- Setup is a terminal wizard (`python -m ufo.setup`); keep it testable via the `Prompter` interface and never print secrets. Telegram bot creation cannot be automated (BotFather), everything after it can.
- The daily run is a macOS launch agent (`com.ufo.daily-check`, `ufo/setup/schedule.py`); it holds no secrets (the job reads `.env` from the project folder).
- US accounts and USD only for now; foreign-currency and international scenarios are deprioritized.
- Messages access (`partner/imessage.py`) is read-only on the user's own chat.db, limited to one person's messages in configured chats. Never write message text to disk, logs, tests, issues, PRs or commits; tests use invented messages. `.data/partner.json` is local only.
- The check walks the running Joint balance through the window (bills out, scheduled deposits in; same-day bills first) and compares the lowest point to the cushion. Rent counts as $0 unless `rent_paid_from_joint`. Bills in v1: credit cards (statement balance via Plaid Liabilities) and manual bills; other categories are a later stage.
- Prefer small pure functions with tests; add infrastructure (db, api, queues) only when a feature needs it.
