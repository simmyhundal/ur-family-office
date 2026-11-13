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

/** Headline numbers for one simulated path. `rf` is the cash rate in percent a year: a flat number, or an array with
 *  one value per date (the rate at the start of each month's return), or null when unknown (Sharpe is then null). */
export function metrics(sim, rf = null) {
  const months = sim.returns.length;
  const growth = growthIndex(sim.returns);
  const g = growth[growth.length - 1];
  const rfAt = (k) => (Array.isArray(rf) ? rf[k] : rf);
  const known = rf != null && Array.from({ length: months }, (_, k) => rfAt(k)).every((x) => x != null);
  const excess = known ? sim.returns.map((r, k) => r - monthlyRf(rfAt(k))) : [];
  const enough = months >= 12;
  const sd = months > 1 ? stdev(sim.returns) : NaN;
  const exSd = known && months > 1 ? stdev(excess) : NaN;
  return {
    endValue: sim.values[sim.values.length - 1],
    putIn: sim.putIn,
    gain: sim.values[sim.values.length - 1] - sim.putIn,
    totalReturn: g - 1, // time-weighted: ignores when money went in
    annualReturn: enough && g > 0 ? g ** (12 / months) - 1 : null,
    volatility: enough ? sd * Math.sqrt(12) : null,
    sharpe: known && enough && exSd > 1e-12 ? (mean(excess) / exSd) * Math.sqrt(12) : null,
    maxDrawdown: maxDrawdown(growth),
    months,
  };
}

/** Compare a mix against one benchmark symbol (100% in it, same strategy and same deposits). */
export function compare({ prices, mix, benchmark, initial = 10000, monthly = 0, strategy = "hold", rf = null }) {
  const a = simulate({ prices, weights: mix, initial, monthly, strategy });
  const b = simulate({ prices, weights: { [benchmark]: 1 }, initial, monthly, strategy });
  return { mix: { sim: a, m: metrics(a, rf) }, bench: { sim: b, m: metrics(b, rf) } };
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
  if (head.includes("open") && (head.includes("adj close") || head.includes("adj_close")))
    throw new Error("This looks like a single-fund download (Open, High, Low, Adj Close). Put one adjusted-price column per fund in one file, or use the date,symbol,price layout.");
  const obs = {}; // symbol -> Map(dateISO -> price)
  const long = head.length === 3 && ["symbol", "ticker"].includes(head[1]);
  if (long) {
    for (const [d, sym, p] of rows) if (p !== "" && p !== undefined) (obs[sym.toUpperCase()] ??= new Map()).set(d, Number(p));
  } else {
    const syms = split(lines[0]).slice(1).map((s) => s.toUpperCase());
    syms.forEach((s) => (obs[s] = new Map()));
    // A blank cell means "no price yet" (a fund that started later than the others); toMonthly then drops those months.
    for (const r of rows) syms.forEach((s, i) => { if (r[i + 1] !== "" && r[i + 1] !== undefined) obs[s].set(r[0], Number(r[i + 1])); });
  }
  for (const [s, m] of Object.entries(obs))
    for (const [d, p] of m) if (!/^\d{4}-\d{2}-\d{2}$/.test(d) || !(p > 0)) throw new Error(`Bad row for ${s} on "${d}": dates must be YYYY-MM-DD and prices above zero.`);
  const empty = Object.keys(obs).filter((s) => obs[s].size === 0);
  if (empty.length || !Object.keys(obs).length) throw new Error(`No prices found for ${empty.join(", ") || "any fund"}.`);
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

/** Completed months only: drop every date whose month has not ended yet on `today` ("YYYY-MM-DD", local date).
 *  A month-end counts once the calendar has moved into a later month. Dates, every series and a per-date `rf` are cut together. */
export function completedMonths(d, today) {
  const cut = String(today).slice(0, 7);
  let n = d.dates.length;
  while (n > 0 && d.dates[n - 1].slice(0, 7) >= cut) n--;
  if (n === d.dates.length) return d;
  return { ...d, dates: d.dates.slice(0, n), series: Object.fromEntries(Object.entries(d.series).map(([s, v]) => [s, v.slice(0, n)])),
    rf: Array.isArray(d.rf) ? d.rf.slice(0, n) : d.rf };
}
export const localToday = (now = new Date()) =>
  `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
/** "2026-10-30" -> "Oct 2026", without time zones. */
export const throughLabel = (iso) => `${MONTHS[Number(iso.slice(5, 7)) - 1]} ${iso.slice(0, 4)}`;

/** Months to use for these symbols: from the latest first-price to the end, then the last `years` of that.
 *  A fund that started later shortens the period; `from` says which symbol set the start. */
export function sliceFor(data, symbols, years) {
  let first = 0, limiter = null;
  for (const s of symbols) {
    const i = data.series[s].findIndex((v) => v != null);
    if (i < 0) throw new Error(`No prices for ${s}.`);
    if (i > first) { first = i; limiter = s; }
  }
  const n = data.dates.length - first;
  const from = first + Math.max(0, n - (years * 12 + 1));
  return {
    rf: Array.isArray(data.rf) ? data.rf.slice(from) : (data.rf ?? null),
    dates: data.dates.slice(from),
    series: Object.fromEntries(symbols.map((s) => [s, data.series[s].slice(from)])),
    limitedBy: from === first ? limiter : null, // set only when the start came from a late fund, not from the period
  };
}

// ---------- the "How Sharpe works" lesson: every step of the Sharpe ratio, shown separately ----------

/** Month-to-month returns of one price series. */
export const priceReturns = (p) => p.slice(1).map((v, i) => v / p[i] - 1);

/** Pearson correlation of two equal-length series. */
export function correlation(a, b) {
  const ma = mean(a), mb = mean(b);
  let sab = 0, saa = 0, sbb = 0;
  for (let i = 0; i < a.length; i++) { sab += (a[i] - ma) * (b[i] - mb); saa += (a[i] - ma) ** 2; sbb += (b[i] - mb) ** 2; }
  return sab / Math.sqrt(saa * sbb);
}

/** The Sharpe ratio in steps (same arithmetic as metrics()). `rf` as in metrics(). Returns null when there is no
 *  cash rate. `within` counts the months that landed within one standard deviation of the average excess return. */
export function sharpeSteps(returns, rf) {
  const rfAt = (k) => (Array.isArray(rf) ? rf[k] : rf);
  if (rf == null || returns.some((_, k) => rfAt(k) == null) || returns.length < 2) return null;
  const cash = returns.map((_, k) => monthlyRf(rfAt(k)));
  const excess = returns.map((r, k) => r - cash[k]);
  const meanExcess = mean(excess), sd = stdev(excess);
  return {
    n: returns.length, cash, excess, meanCash: mean(cash), meanExcess, sd,
    meanExcessAnnual: meanExcess * 12, sdAnnual: sd * Math.sqrt(12),
    sharpe: sd > 1e-12 ? (meanExcess / sd) * Math.sqrt(12) : null,
    within: excess.filter((x) => Math.abs(x - meanExcess) <= sd).length,
    compoundedAnnual: growthIndex(returns).at(-1) ** (12 / returns.length) - 1,
  };
}

/** Two funds, mixed 50/50 each month: volatility of the mix versus the plain average of the two volatilities. */
export function blend5050(a, b) {
  const ann = (x) => stdev(x) * Math.sqrt(12);
  const volA = ann(a), volB = ann(b), volMix = ann(a.map((x, i) => (x + b[i]) / 2));
  return { volA, volB, volAvg: (volA + volB) / 2, volMix, corr: correlation(a, b) };
}
