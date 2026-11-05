# ur-family-office

- v1 is **read-only**. Never add code that moves money or submits orders; Phase 2 execution needs its own design, approvals and a broker partner (Fidelity has no trading API).
- Secrets (Plaid tokens, Twilio keys, account numbers, CSV exports) never go in the repo. `.env`, `.data/`, `*.csv` are gitignored; keep it that way.
- Financial output is information, not advice; keep the disclaimer in user-facing text.
- The rebalance engine is a port of the Node prototype in `~/code/fin-advisor` (`src/rebalance.mjs`, `trades.mjs`, `plan.mjs`, `csv.mjs`). Its tests are the spec: port them first, then the code. Target weights come from the user's Redistribution Google Sheet, not hard-coded values.
- Plaid's holdings omit the cash/money-market sweep; derive it as `balances.current - sum(holdings)`.
- Prefer small pure functions with tests; add infrastructure (db, api, queues) only when a feature needs it.
