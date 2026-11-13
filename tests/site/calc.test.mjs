// Known-answer tests for site/js/calc.mjs. Every number is invented.   Run: node --test tests/site/
import test from "node:test";
import assert from "node:assert/strict";
import { sliceFor, simulate, metrics, compare, parsePricesCsv, toMonthly, normalizeWeights, maxDrawdown } from "../../site/js/calc.mjs";

const close = (a, b, eps = 1e-9) => assert.ok(Math.abs(a - b) < eps, `${a} vs ${b}`);

test("buy and hold: one fund doubles, the other is flat", () => {
  const prices = { A: [1, 2], B: [1, 1] };
  const s = simulate({ prices, weights: { A: 50, B: 50 }, initial: 1000 });
  close(s.values[1], 1500);
  close(s.returns[0], 0.5);
});

test("monthly rebalance resets to the target weights", () => {
  const prices = { A: [1, 2, 2], B: [1, 1, 2] };
  const s = simulate({ prices, weights: { A: 1, B: 1 }, initial: 1000, strategy: "monthly" });
  // month 1: 500+500 -> A 1000 + B 500 = 1500, reset to 750/750. month 2: A flat, B doubles -> 750 + 1500 = 2250
  close(s.values[1], 1500);
  close(s.values[2], 2250);
  close(s.returns[1], 0.5);
});

test("annual rebalance only happens every twelfth month", () => {
  const n = 13;
  const A = Array.from({ length: n }, (_, i) => (i === 0 ? 1 : 2));
  const B = Array(n).fill(1);
  const hold = simulate({ prices: { A, B }, weights: { A: 1, B: 1 }, initial: 1000, strategy: "hold" });
  const annual = simulate({ prices: { A, B }, weights: { A: 1, B: 1 }, initial: 1000, strategy: "annual" });
  close(hold.values[11], annual.values[11]); // identical until the first rebalance
  close(annual.values[12], 1500); // still 1500: rebalancing changes weights, not value
});

test("a single holding is the same under every strategy", () => {
  const prices = { A: [10, 11, 9, 12, 13] };
  const out = ["hold", "monthly", "annual"].map((strategy) => simulate({ prices, weights: { A: 1 }, initial: 500, monthly: 100, strategy }).values.at(-1));
  close(out[0], out[1]);
  close(out[0], out[2]);
});

test("flat prices: value equals what was put in, deposits split by weight", () => {
  const prices = { A: Array(6).fill(5), B: Array(6).fill(8) };
  const s = simulate({ prices, weights: { A: 3, B: 1 }, initial: 1000, monthly: 200 });
  close(s.values.at(-1), 2000);
  close(s.putIn, 2000);
  const m = metrics(s);
  close(m.gain, 0);
  close(m.totalReturn, 0);
});

test("a deposit after the return does not count as performance", () => {
  const prices = { A: [1, 2] };
  const s = simulate({ prices, weights: { A: 1 }, initial: 1000, monthly: 1000 });
  close(s.returns[0], 1);
  close(s.values[1], 3000);
});

test("max drawdown is the worst fall from a peak", () => {
  close(maxDrawdown([1.1, 1.3, 0.65, 0.9]), -0.5);
});

test("annualized figures need at least twelve months", () => {
  const short = metrics(simulate({ prices: { A: [1, 1.1, 1.2] }, weights: { A: 1 }, initial: 100 }));
  assert.equal(short.annualReturn, null);
  assert.equal(short.sharpe, null);
  const prices = { A: Array.from({ length: 25 }, (_, i) => 100 * 1.01 ** i) };
  const long = metrics(simulate({ prices, weights: { A: 1 }, initial: 100 }));
  close(long.annualReturn, 1.01 ** 12 - 1, 1e-9);
  assert.equal(long.sharpe, null); // zero variance: no meaningful Sharpe
});

test("compare uses the same strategy and deposits for the benchmark", () => {
  const prices = { A: [1, 1.2, 1.1], B: [1, 1.1, 1.3] };
  const r = compare({ prices, mix: { A: 1 }, benchmark: "B", initial: 1000, monthly: 100 });
  close(r.mix.m.putIn, r.bench.m.putIn);
});

test("rejects missing prices and empty weights", () => {
  assert.throws(() => simulate({ prices: { A: [1, 0] }, weights: { A: 1 }, initial: 10 }), /non-positive/);
  assert.throws(() => normalizeWeights({ A: 0 }), /at least one/);
  assert.throws(() => simulate({ prices: { A: [1, 2] }, weights: { A: 1 }, initial: 10, strategy: "daily" }), /Unknown strategy/);
});

test("CSV: wide layout, last observation of each month", () => {
  const d = parsePricesCsv("date,AAA,BBB\n2024-01-15,10,20\n2024-01-31,11,21\n2024-02-29,12,22\n");
  assert.deepEqual(d.dates, ["2024-01-31", "2024-02-29"]);
  assert.deepEqual(d.series.AAA, [11, 12]);
});

test("CSV: long layout, and months missing for a symbol are dropped", () => {
  const d = parsePricesCsv("date,symbol,price\n2024-01-31,aaa,10\n2024-02-29,aaa,11\n2024-03-29,aaa,12\n2024-01-31,bbb,5\n2024-03-29,bbb,6\n");
  assert.deepEqual(d.dates, ["2024-01-31", "2024-03-29"]);
  assert.equal(d.dropped, 1);
});

test("CSV: bad input gets a plain message", () => {
  assert.throws(() => parsePricesCsv("when,AAA\n1,2\n3,4"), /called "date"/);
  assert.throws(() => parsePricesCsv("date,AAA\n2024-01-31,abc\n2024-02-29,3"), /Bad row/);
  assert.throws(() => parsePricesCsv("date,AAA\n2024-01-31,1"), /at least two/);
});

test("CSV: a blank cell means the fund had not started yet, those months are dropped", () => {
  const d = parsePricesCsv("date,AAA,BBB\n2024-01-31,10,\n2024-02-29,11,\n2024-03-29,12,5\n2024-04-30,13,6\n");
  assert.deepEqual(d.dates, ["2024-03-29", "2024-04-30"]);
  assert.deepEqual(d.series.BBB, [5, 6]);
  assert.equal(d.dropped, 2);
});

test("CSV: a column with no prices at all is reported by name", () => {
  assert.throws(() => parsePricesCsv("date,AAA,BBB\n2024-01-31,10,\n2024-02-29,11,\n"), /No prices found for BBB/);
});

test("CSV: a single-fund download from a price site gets a plain explanation", () => {
  assert.throws(() => parsePricesCsv("Date,Open,High,Low,Close,Adj Close,Volume\n2024-01-31,1,2,1,2,2,5\n2024-02-29,1,2,1,2,2,5\n"), /single-fund download/);
});

test("daily prices with weekends, holidays and a later-starting fund line up on real month-ends", () => {
  // Invented business-day series for three years; the second fund starts 14 months in (blank before that).
  const lines = ["date,AAA,BBB"];
  let day = 0;
  for (let t = Date.UTC(2021, 0, 1); t < Date.UTC(2024, 0, 1); t += 86400000) {
    const dt = new Date(t), wd = dt.getUTCDay();
    if (wd === 0 || wd === 6) continue; // no weekend prices
    if (dt.getUTCMonth() === 6 && dt.getUTCDate() === 4) continue; // a holiday
    day++;
    const a = (100 * 1.0004 ** day).toFixed(4);
    const b = t >= Date.UTC(2022, 2, 1) ? (50 * 1.0002 ** day).toFixed(4) : "";
    lines.push(`${dt.toISOString().slice(0, 10)},${a},${b}`);
  }
  const d = parsePricesCsv(lines.join("\n"));
  assert.equal(d.dates[0].slice(0, 7), "2022-03"); // first month both funds have prices
  assert.equal(d.dates.at(-1).slice(0, 7), "2023-12");
  assert.equal(d.dates.length, 22);
  for (const iso of d.dates) {
    const dt = new Date(iso + "T00:00:00Z"), next = new Date(dt.getTime() + 86400000 * 3);
    assert.ok(![0, 6].includes(dt.getUTCDay()), iso + " should be a business day");
    assert.notEqual(dt.getUTCMonth(), next.getUTCMonth(), iso + " should be within the last three days of its month");
  }
  const r = compare({ prices: sliceFor(d, ["AAA", "BBB"], 1).series, mix: { AAA: 1, BBB: 1 }, benchmark: "AAA", initial: 1000 });
  assert.ok(r.mix.m.endValue > 1000 && r.bench.m.months === 12);
});

test("sliceFor: a later-starting fund shortens the period and is named", () => {
  const data = { dates: ["a", "b", "c", "d", "e"], series: { SPY: [1, 2, 3, 4, 5], NEW: [null, null, 7, 8, 9] } };
  const w = sliceFor(data, ["SPY", "NEW"], 5);
  assert.deepEqual(w.dates, ["c", "d", "e"]);
  assert.equal(w.limitedBy, "NEW");
  assert.deepEqual(w.series.SPY, [3, 4, 5]);
});

test("sliceFor: the period limit wins when the data is longer, and only chosen symbols count", () => {
  const dates = Array.from({ length: 30 }, (_, i) => `d${i}`);
  const data = { dates, series: { SPY: dates.map((_, i) => i + 1), LATE: dates.map((_, i) => (i < 20 ? null : 1)) } };
  const w = sliceFor(data, ["SPY"], 1);
  assert.equal(w.dates.length, 13);
  assert.equal(w.limitedBy, null);
  assert.throws(() => sliceFor({ dates: ["a"], series: { X: [null] } }, ["X"], 1), /No prices for X/);
});

test("sliceFor: a large period (Max) returns everything the funds share", () => {
  const dates = Array.from({ length: 130 }, (_, i) => `d${i}`);
  const data = { dates, series: { A: dates.map((_, i) => i + 1), B: dates.map((_, i) => (i < 40 ? null : 1)) } };
  assert.equal(sliceFor(data, ["A"], 99).dates.length, 130);
  const w = sliceFor(data, ["A", "B"], 99);
  assert.equal(w.dates.length, 90);
  assert.equal(w.limitedBy, "B");
  assert.equal(sliceFor(data, ["A"], 10).dates.length, 121);
});

test("Sharpe: matches the formula, and a flat or per-month cash rate give the same answer when equal", () => {
  const rets = Array.from({ length: 12 }, (_, i) => (i % 2 ? 0 : 0.02));
  const prices = { A: [100] };
  for (const r of rets) prices.A.push(prices.A.at(-1) * (1 + r));
  const sim = simulate({ prices, weights: { A: 1 }, initial: 1000 });
  const expected = (0.01 / Math.sqrt((12 * 1e-4) / 11)) * Math.sqrt(12);
  close(metrics(sim, 0).sharpe, expected, 1e-9);
  close(metrics(sim, Array(13).fill(0)).sharpe, expected, 1e-9);
  const withRate = metrics(sim, 4).sharpe;
  close(withRate, metrics(sim, Array(13).fill(4)).sharpe, 1e-12);
  assert.ok(withRate < expected, "a positive cash rate lowers Sharpe");
});

test("Sharpe is null when the cash rate is unknown or a month's rate is missing", () => {
  const prices = { A: Array.from({ length: 14 }, (_, i) => 100 + i * (i % 3)) };
  const sim = simulate({ prices, weights: { A: 1 }, initial: 1000 });
  assert.equal(metrics(sim, null).sharpe, null);
  assert.equal(metrics(sim, [1, null, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1]).sharpe, null);
  assert.notEqual(metrics(sim, 1).sharpe, null);
});

test("sliceFor carries the cash-rate array along with the dates", () => {
  const data = { dates: ["a", "b", "c", "d"], series: { A: [1, 2, 3, 4] }, rf: [1, 2, 3, 4] };
  assert.deepEqual(sliceFor(data, ["A"], 1).rf, [1, 2, 3, 4]);
  const long = { dates: Array.from({ length: 30 }, (_, i) => `d${i}`), series: { A: Array(30).fill(1) }, rf: Array.from({ length: 30 }, (_, i) => i) };
  const w = sliceFor(long, ["A"], 1);
  assert.equal(w.rf.length, 13);
  assert.equal(w.rf[0], 17);
});

import { sharpeSteps, correlation, blend5050, priceReturns } from "../../site/js/calc.mjs";

test("sharpeSteps: agrees with metrics() and counts months within one standard deviation", () => {
  const prices = { A: [100] };
  for (const r of [0.02, -0.01, 0.03, 0.0, 0.01, -0.02, 0.04, 0.01, -0.01, 0.02, 0.0, 0.03]) prices.A.push(prices.A.at(-1) * (1 + r));
  const sim = simulate({ prices, weights: { A: 1 }, initial: 1000 });
  const s = sharpeSteps(sim.returns, 4);
  close(s.sharpe, metrics(sim, 4).sharpe, 1e-12);
  close(s.meanExcessAnnual / s.sdAnnual, s.sharpe, 1e-12); // "divide" step equals the code's monthly route
  close(s.meanCash, (1.04) ** (1 / 12) - 1, 1e-12);
  assert.equal(s.n, 12);
  assert.ok(s.within >= 6 && s.within <= 12);
  assert.equal(sharpeSteps(sim.returns, null), null);
  assert.equal(sharpeSteps(sim.returns, Array(12).fill(null)), null);
});

test("correlation and the 50/50 blend: known answers", () => {
  close(correlation([1, 2, 3], [2, 4, 6]), 1);
  close(correlation([1, 2, 3], [3, 2, 1]), -1);
  const a = [0.01, -0.02, 0.03, 0.0], b = [-0.01, 0.02, -0.03, 0.0];
  const m = blend5050(a, b);
  close(m.corr, -1);
  close(m.volMix, 0, 1e-12); // perfectly opposite funds cancel
  assert.ok(m.volMix < m.volAvg);
  const same = blend5050(a, a); // identical funds: no benefit
  close(same.volMix, same.volAvg, 1e-12);
  close(priceReturns([100, 110, 99])[1], -0.1);
});
