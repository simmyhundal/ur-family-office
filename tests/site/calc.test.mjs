// Known-answer tests for site/js/calc.mjs. Every number is invented.   Run: node --test tests/site/
import test from "node:test";
import assert from "node:assert/strict";
import { simulate, metrics, compare, parsePricesCsv, toMonthly, window, normalizeWeights, maxDrawdown } from "../../site/js/calc.mjs";

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

test("window keeps the last N years of month-ends plus the start point", () => {
  const dates = Array.from({ length: 80 }, (_, i) => `d${i}`);
  const w = window({ dates, series: { A: dates.map((_, i) => i + 1) } }, 5);
  assert.equal(w.dates.length, 61);
  assert.equal(w.dates.at(-1), "d79");
  assert.equal(window({ dates: ["a", "b"], series: { A: [1, 2] } }, 5).dates.length, 2);
});
