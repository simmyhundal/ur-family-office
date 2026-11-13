<!--
Lesson template for the dashboard tab "How Sharpe works".
Every {placeholder} is filled at render time from the owner's local data (never stored in the repo).
Placeholders that can't be computed render as "n/a" with the reason. Keep the arithmetic here identical to
src/ufo/performance/metrics.py: sharpe() = mean(monthly excess) / stdev(monthly excess) * sqrt(12).
-->

# How the Sharpe ratio is calculated, using your portfolio

## The question it answers

Two portfolios can both return 10% a year. If one got there with calm, steady months and the other swung up and down 20% along the way, most people would rather have the first. The Sharpe ratio puts a number on that: **how much return you earned above cash, for each unit of ups and downs you lived through.**

Your whole portfolio ("{portfolio_name}") has a Sharpe ratio of **{sharpe}**, measured over {n_months} months ({start_month} to {end_month}). {benchmark} over the same months: **{benchmark_sharpe}**. Here is where those numbers come from.

## Step 1: one return per month

For each month we take the value at the end, remove what you deposited or withdrew that month, and compare it with the value at the start. Deposits are not returns, so they must be taken out.

Your most recent month, {example_month}, worked out:

| | |
|---|---|
| Value at the start of the month | {ex_start_value} |
| Deposits minus withdrawals during the month | {ex_net_flow} |
| Value at the end of the month | {ex_end_value} |
| Gain from the investments themselves | {ex_gain} |
| **Return for the month** | **{ex_return}** |

Your last twelve months:

{monthly_table}
<!-- columns: Month | Return | Cash (T-bill) for the month | Return above cash -->

{estimate_note}
<!-- e.g. "Month-end values for some accounts are rebuilt from transactions and prices, so these returns are estimates. The money-weighted IRR elsewhere on the dashboard is exact." -->

## Step 2: subtract what cash would have paid

Any money could have sat in 3-month US Treasury bills, close to risk-free. Over these months that paid about **{rf_annual}** a year, or **{rf_month}** a month. Only the return *above* that counts as a reward for taking risk, so each month's return minus the T-bill rate is the **excess return** (last column above).

## Step 3: average the excess returns

Your average monthly excess return was **{mean_excess_month}**. Times 12, that is about **{mean_excess_annual}** a year.

## Step 4: measure how bumpy the ride was

Volatility is the standard deviation of those monthly excess returns: roughly, how far a typical month lands from the average. Yours is **{sd_month}** a month. Monthly swings don't add up twelve-fold over a year, because good and bad months partly cancel, so the yearly figure scales by √12 (about 3.46): **{sd_annual}** a year.

## Step 5: divide

**Sharpe = average excess return ÷ volatility**

{mean_excess_annual} ÷ {sd_annual} = **{sharpe}**

(The code does the same sum in monthly units: {mean_excess_month} ÷ {sd_month} × √12. The answer is identical.)

## Reading the number

- **Higher is better.** It is return per unit of risk.
- **Rough guide over long periods:** below 0.5 is modest, around 1 is good, and above 1.5 is rare and often doesn't last. Short windows can show almost anything.
- **Compare like with like:** same months, same cash rate. That is why every account and {benchmark} on this dashboard use the same window.
- **Limits:**
  - It treats a surprise gain as "risk" just like a loss. The Sortino ratio counts only downside months; yours is {sortino}.
  - It assumes returns are roughly bell-shaped, and crashes are more common than that.
  - With fewer than about 36 months it is noisy.
- **Left out:** {excluded_accounts} have no market prices, so they have no volatility and no Sharpe ratio.

## How this connects to modern portfolio theory

In 1952 Harry Markowitz showed that what matters is not each investment on its own, but how they move **together**.

**1. Mixing lowers risk when things don't move in lockstep.** Two of your accounts, {acct_a} and {acct_b}, have volatilities of {vol_a} and {vol_b}. Their monthly returns have a correlation of {corr_ab}: 1.0 would mean they always move together, 0 not at all. A 50/50 mix of the two would have had a volatility of **{vol_mix}**, below the simple average of {vol_avg}. That gap is the diversification benefit: lower risk without giving up the average return.

**2. The efficient frontier.** Try every possible mix of a set of investments and plot each one's risk and return. The upper-left edge of that cloud is the efficient frontier: for each level of risk, the highest return any mix achieved. Mixes below the edge take risk without being paid for it.

**3. The Sharpe ratio is a slope.** On the Risk vs return chart, put a point at zero risk and the T-bill return ({rf_annual}). Draw a line from it to any portfolio. The steepness of that line *is* the portfolio's Sharpe ratio: extra return per unit of extra risk. Your portfolio's line has slope {sharpe}; {benchmark}'s has slope {benchmark_sharpe}.

**4. The best mix touches the frontier.** The steepest line that still reaches the frontier touches it at one mix: the **maximum-Sharpe (tangency) portfolio**. Theory says every investor should hold that mix and adjust risk only by adding cash (less risk) or leverage (more). In practice the frontier is drawn from past returns, which shift, so the "best" mix is an estimate, not a promise.

**What's next:** a suggested max-Sharpe mix for your holdings is planned (issue 130). It will use this same arithmetic, with guardrails against trusting the past too much.

*Figures are before tax. Information, not investment advice.*
