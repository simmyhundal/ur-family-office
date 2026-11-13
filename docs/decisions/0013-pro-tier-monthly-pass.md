# 0013: A premium research tier, sold as a monthly pass

Status: accepted as direction by the owner (2026-11-13). Name, price and launch are open (below). Builds on 0012 (sign-ups and payments). Not financial or legal advice; legal review is [issue 62](https://github.com/simmyhundal/ur-family-office/issues/62).

## Context
The owner's view: retail investors will not succeed as "day trade" professionals, and the product should not push them to trade often. Most people make a real portfolio decision only a few times a year, such as a new job, a rollover, a lump sum or a yearly rebalance. The deeper research tools built for the Plus track are what someone wants at those moments, not every day:
- what-if backtests with rolling windows and a replay of the user's own deposits and withdrawals (`jobs/whatif.py`);
- the max-Sharpe frontier with a walk-forward test (`jobs/whatif_sharpe.py`).

## Decision
1. **Three paid levels of depth.**
   - **Free:** the site as today.
   - **Plus:** every account side by side, the dashboard.
   - **A higher tier** (working name **Pro**; final name open): advanced research charts and reports. These include the what-if scenarios, the Sharpe report with the best-Sharpe mix and its frontier, and later research from milestone M12.
   - Pro includes everything in Plus.
2. **Price: about 10x Plus.** Plus is listed at $4/month, so Pro is about $40 for a month. The exact number is open.
3. **Sold as a one-month pass, not an auto-renewing subscription.** Buying Pro unlocks it for one month. When the month ends, the account drops back to Plus by itself unless the user buys another month. No surprise renewals, no cancel flow to hunt for.
   - It fits the use: people buy a month when they have a decision to make.
   - It sells depth of research, not activity: nothing in Pro is built around trading frequency.
4. **Honesty rules carry over unchanged.** Every Pro scenario shows the out-of-sample or walk-forward result first, start-date sensitivity, assumptions (pre-tax, fees inside prices, no trading costs, stand-ins named) and the disclaimer. A backtest winner is never shown as a prediction, and the hindsight answer is labelled as hindsight. Paying more never buys a rosier number.
5. **Local-first still holds.** Pro analyses run on the user's computer like Plus; no portfolio data is uploaded (0011, 0012).

## Open questions (each needs an answer before launch)
- **Legal, first.** A paid tier that shows a *suggested mix for your own holdings* is closer to personalized investment advice than a general tool. Before Pro is sold, legal review (issue 62) must say whether this needs adviser registration or how it must be framed. It must also settle the rules for showing hypothetical (backtested) performance. Until then Pro is "planned" on the site, like Plus.
- **Entitlements without uploading data.** 0012 keeps paid features on the waitlist until there is a way to unlock them. Because analysis is local, the likely shape is a signed licence key with an expiry date, checked offline by the local tool, issued after payment, and lapsing to Plus on its own. That needs its own decision.
- **Payments.** A one-time Payment Link per month fits 0012 (no card data on the site). Check whether the payment provider can issue the licence key automatically.
- **What stays in Plus.** `site/data/plans.json` lists "Test a change before you make it" under Plus. Decide the line: for example, Plus keeps one simple what-if (one mix against one benchmark, since inception), and Pro gets rolling windows, flow replay, the frontier and walk-forward tests. `plans.json` is a site-track file, so that change goes in its own small PR.
- **Name and exact price,** and whether a student or class price exists (see [issue 183](https://github.com/simmyhundal/ur-family-office/issues/183)).

## Consequences
The Plus track builds research features as Pro features, flagged, from now on. The pricing page needs a third paid column and the words "one month, no auto-renew". Nothing here changes the read-only rule (0002) or the IBKR execution gate (decision 0010, [issue 73](https://github.com/simmyhundal/ur-family-office/issues/73)).
