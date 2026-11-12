// Mix-vs-benchmark maths. Pure functions, no I/O, no DOM: the page and the tests share this file.
// Conventions match src/ufo/performance/metrics.py so the two can be checked against each other:
//   - prices are month-end adjusted (total-return) closes
//   - the first date is the purchase date; each later month-end gets that month's contribution AFTER the month's return
//   - monthly return = value before the new deposit / previous value - 1 (exact time-weighted for end-of-month deposits)
//   - Sharpe = mean(excess) / sample stdev(excess) * sqrt(12); volatility = sample stdev * sqrt(12)

export const STRATEGIES = ["hold", "monthly", "annual"];

export function normalizeWeights(weights) {
  const entries = Object.entries(weights).filter(([, w]) => w > 0);
  const total = entries.reduce((s, [, w]) => s + w, 0);
  if (!entries.length || !(total > 0)) throw new Error("Give at least one holding a weight above zero.");
  return Object.fromEntries(entries.map(([s, w]) => [s, w / total]));
}

/** Simulate one portfolio over month-end prices. Returns dollar values, monthly returns and what was put in. */
export function simulate({ prices, weights, initial, monthly = 0, strategy = "hold" }) {
  if (!STRATEGIES.includes(strategy)) throw new Error(`Unknown strategy: ${strategy}`);
  const w = normalizeWeights(weights);
  const symbols = Object.keys(w);
  const n = prices[symbols[0]].length;
  for (const s of symbols) {
    if (!prices[s] || prices[s].length !== n) throw new Error(`Prices for ${s} do not line up with the other dates.`);
    if (prices[s].some((p) => !(p > 0))) throw new Error(`${s} has a missing or non-positive price in this window.`);
  }
  const units = Object.fromEntries(symbols.map((s) => [s, (initial * w[s]) / prices[s][0]]));
  const values = [initial];
  const returns = [];
  const contributed = [initial];
  let put = initial;
  const worth = (i) => symbols.reduce((sum, s) => sum + units[s] * prices[s][i], 0);
  for (let i = 1; i < n; i++) {
    const before = worth(i);
    returns.push(before / values[i - 1] - 1);
    if (monthly > 0) {
      for (const s of symbols) units[s] += (monthly * w[s]) / prices[s][i];
      put += monthly;
    }
    let after = worth(i);
    const rebalance = strategy === "monthly" || (strategy === "annual" && i % 12 === 0);
    if (rebalance) {
      for (const s of symbols) units[s] = (after * w[s]) / prices[s][i];
      after = worth(i);
    }
    values.push(after);
    contributed.push(put);
  }
  return { values, returns, contributed, putIn: put };
}

export const mean = (xs) => xs.reduce((a, b) => a + b, 0) / xs.length;
export function stdev(xs) {
  const m = mean(xs);
  return Math.sqrt(xs.reduce((s, x) => s + (x - m) ** 2, 0) / (xs.length - 1));
}
export function growthIndex(returns) {
  let g = 1;
  return returns.map((r) => (g *= 1 + r));
}
export function maxDrawdown(growth) {
  let peak = 1, worst = 0;
  for (const v of growth) {
    peak = Math.max(peak, v);
    worst = Math.min(worst, v / peak - 1);
  }
  return worst;
}
export const monthlyRf = (annualPercent) => (1 + annualPercent / 100) ** (1 / 12) - 1;

/** Headline numbers for one simulated path. rfAnnualPercent is a flat T-bill yield in percent (default 0). */
export function metrics(sim, rfAnnualPercent = 0) {
  const months = sim.returns.length;
  const growth = growthIndex(sim.returns);
  const g = growth[growth.length - 1];
  const rf = monthlyRf(rfAnnualPercent);
  const excess = sim.returns.map((r) => r - rf);
  const enough = months >= 12;
  const sd = months > 1 ? stdev(sim.returns) : NaN;
  const exSd = months > 1 ? stdev(excess) : NaN;
  return {
    endValue: sim.values[sim.values.length - 1],
    putIn: sim.putIn,
    gain: sim.values[sim.values.length - 1] - sim.putIn,
    totalReturn: g - 1, // time-weighted: ignores when money went in
    annualReturn: enough && g > 0 ? g ** (12 / months) - 1 : null,
    volatility: enough ? sd * Math.sqrt(12) : null,
    sharpe: enough && exSd > 1e-12 ? (mean(excess) / exSd) * Math.sqrt(12) : null,
    maxDrawdown: maxDrawdown(growth),
    months,
  };
}

/** Compare a mix against one benchmark symbol (100% in it, same strategy and same deposits). */
export function compare({ prices, mix, benchmark, initial = 10000, monthly = 0, strategy = "hold", rfAnnualPercent = 0 }) {
  const a = simulate({ prices, weights: mix, initial, monthly, strategy });
  const b = simulate({ prices, weights: { [benchmark]: 1 }, initial, monthly, strategy });
  return { mix: { sim: a, m: metrics(a, rfAnnualPercent) }, bench: { sim: b, m: metrics(b, rfAnnualPercent) } };
}

// ---------- data: month-end prices ----------

const isoMonth = (d) => d.slice(0, 7);

/** Parse CSV text into {dates, series}. Wide (date,SYM1,SYM2,...) or long (date,symbol,price) layouts. */
export function parsePricesCsv(text) {
  const lines = text.trim().split(/\r?\n/).filter((l) => l.trim());
  if (lines.length < 3) throw new Error("The file needs a header row and at least two rows of prices.");
  const split = (l) => l.split(",").map((c) => c.trim().replace(/^"|"$/g, ""));
  const head = split(lines[0]).map((h) => h.toLowerCase());
  if (head[0] !== "date") throw new Error('The first column must be called "date".');
  const rows = lines.slice(1).map(split);
  const obs = {}; // symbol -> Map(dateISO -> price)
  const long = head.length === 3 && ["symbol", "ticker"].includes(head[1]);
  if (long) {
    for (const [d, sym, p] of rows) (obs[sym.toUpperCase()] ??= new Map()).set(d, Number(p));
  } else {
    const syms = split(lines[0]).slice(1).map((s) => s.toUpperCase());
    syms.forEach((s) => (obs[s] = new Map()));
    for (const r of rows) syms.forEach((s, i) => obs[s].set(r[0], Number(r[i + 1])));
  }
  for (const [s, m] of Object.entries(obs))
    for (const [d, p] of m) if (!/^\d{4}-\d{2}-\d{2}$/.test(d) || !(p > 0)) throw new Error(`Bad row for ${s} on "${d}": dates must be YYYY-MM-DD and prices above zero.`);
  return toMonthly(obs);
}

/** Keep the last observation in each month, then only the months every symbol has. */
export function toMonthly(obs) {
  const perSym = {};
  for (const [s, m] of Object.entries(obs)) {
    const byMonth = new Map();
    for (const d of [...m.keys()].sort()) byMonth.set(isoMonth(d), [d, m.get(d)]);
    perSym[s] = byMonth;
  }
  const syms = Object.keys(perSym);
  let months = [...perSym[syms[0]].keys()];
  for (const s of syms.slice(1)) months = months.filter((mo) => perSym[s].has(mo));
  months.sort();
  const dates = months.map((mo) => perSym[syms[0]].get(mo)[0]);
  const series = Object.fromEntries(syms.map((s) => [s, months.map((mo) => perSym[s].get(mo)[1])]));
  return { dates, series, dropped: Math.max(...syms.map((s) => perSym[s].size)) - months.length };
}

/** Last `years` of data (years*12 months after the start date), or all of it if shorter. */
export function window(data, years) {
  const n = data.dates.length;
  const keep = Math.min(n, years * 12 + 1);
  const from = n - keep;
  return { dates: data.dates.slice(from), series: Object.fromEntries(Object.entries(data.series).map(([s, v]) => [s, v.slice(from)])) };
}
