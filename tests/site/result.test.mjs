// The completed-month cutoff and the shared result that Home, Try and the lesson all use. Every number is invented,
// except the bundled demo prices, which are invented funds.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { completedMonths, throughLabel, compare, sliceFor } from "../../site/js/calc.mjs";
import { runResult, sampleConfig, previewModel, headline, nextStep, defaultBenchmark, OTHER, SAMPLE } from "../../site/js/result.mjs";
import { loadPrices } from "../../site/js/data.mjs";
import { soWhat, sharpeBand, lessonModel } from "../../site/js/lesson.mjs";

const demoFile = JSON.parse(readFileSync(new URL("../../site/data/demo-prices.json", import.meta.url), "utf8"));
const demo = { dates: demoFile.dates, series: demoFile.series, rf: demoFile.rf ?? null };

// ---------- completed months only ----------
test("cutoff: a month counts once it has ended; the current month is dropped", () => {
  const d = { dates: ["2026-09-30", "2026-10-30", "2026-11-12"], series: { A: [1, 2, 3], B: [4, 5, 6] }, rf: [4, 4.1, 4.2] };
  const c = completedMonths(d, "2026-11-13");
  assert.deepEqual(c.dates, ["2026-09-30", "2026-10-30"]);
  assert.deepEqual(c.series, { A: [1, 2], B: [4, 5] });
  assert.deepEqual(c.rf, [4, 4.1]); assert.equal(c.rf.length, c.dates.length);
  assert.equal(throughLabel(c.dates.at(-1)), "Oct 2026");
});
test("cutoff: on the first of a month the previous month is complete", () => {
  const d = { dates: ["2026-10-30", "2026-11-28"], series: { A: [1, 2] }, rf: 4 };
  assert.deepEqual(completedMonths(d, "2026-11-30").dates, ["2026-10-30"]);
  assert.deepEqual(completedMonths(d, "2026-12-01").dates, ["2026-10-30", "2026-11-28"]);
  assert.equal(completedMonths(d, "2026-11-30").rf, 4, "a flat rate is kept as is");
});
test("cutoff: data that already ends on a past month is unchanged (the demo set)", () => {
  assert.equal(completedMonths(demo, "2026-11-13"), demo);
  assert.equal(demo.dates.at(-1).slice(0, 7) < "2026-11", true);
});
test("cutoff is applied when prices load, with a 'through' label from the last kept month", async () => {
  const dates = ["2026-08-31", "2026-09-30", "2026-10-30", "2026-11-12"];
  globalThis.UFO_DATA = { asOf: "2026-11-12", dates, series: { SPY: [1, 1.01, 1.02, 1.03] }, rf: [4, 4, 4, 4] };
  globalThis.UFO_PRESETS = [];
  try {
    const p = await loadPrices("2026-11-13");
    assert.deepEqual(p.data.dates, dates.slice(0, 3)); assert.equal(p.data.rf.length, 3);
    assert.equal(p.through, "Oct 2026"); assert.equal(p.source, "Prices through Oct 2026.");
    assert.ok(!p.source.includes("11-12"));
  } finally { delete globalThis.UFO_DATA; delete globalThis.UFO_PRESETS; }
});

// ---------- the Home preview matches Try ----------
test("Home preview is the sample run exactly as Try runs it (demo prices)", () => {
  const cfg = sampleConfig(demo);
  assert.deepEqual(cfg.weights, SAMPLE.demo.weights); assert.equal(cfg.benchmark, defaultBenchmark(demo.series));
  assert.equal(cfg.initial, SAMPLE.initial); assert.equal(cfg.monthly, SAMPLE.monthly); assert.equal(cfg.years, 5);
  const home = previewModel(demo);
  const tryRes = runResult(demo, cfg), tryHead = headline(tryRes, cfg.name);
  for (const k of ["mixAnnual", "benchAnnual", "mixSharpe", "benchSharpe", "diff", "from", "to", "name", "bench"]) assert.equal(home[k], tryHead[k], k);
  // and both equal an independent compare() over the last five years
  const s = sliceFor(demo, [...Object.keys(cfg.weights), cfg.benchmark], 5);
  const r = compare({ prices: s.series, mix: cfg.weights, benchmark: cfg.benchmark, initial: 2000, monthly: 500, rf: s.rf });
  assert.equal(home.mixAnnual, r.mix.m.annualReturn); assert.equal(home.benchSharpe, r.bench.m.sharpe);
  assert.equal(home.months, 60);
});
test("Home and Try share the window: a late-starting 'other' benchmark moves both the same way", () => {
  const n = 30, dates = Array.from({ length: n }, (_, i) => `20${String(20 + Math.floor((i + 1) / 12)).padStart(2, "0")}-${String(((i + 1) % 12) + 1).padStart(2, "0")}-28`);
  const up = (g) => Array.from({ length: n }, (_, i) => 100 * (1 + g) ** i * (1 + 0.02 * Math.sin(i)));
  const series = { VTI: up(0.008), VXUS: up(0.004), BND: up(0.002), QQQ: up(0.01), SPY: up(0.007), IWM: [...Array(6).fill(null), ...up(0.006).slice(6)] };
  const data = { dates, series, rf: 2 };
  const home = previewModel(data), tryRes = runResult(data, sampleConfig(data));
  assert.equal(tryRes.slice.dates[0], dates[6], "IWM starts later, so the shared window starts with it");
  assert.equal(home.from, tryRes.slice.dates[0]);
  assert.equal(home.mixAnnual, tryRes.r.mix.m.annualReturn);
  assert.deepEqual(OTHER.filter((x) => x in series), ["SPY", "VTI", "QQQ", "IWM"]);
});
test("the lesson's first card shows the same two Sharpe ratios as Try", () => {
  const cfg = sampleConfig(demo), res = runResult(demo, cfg);
  const m = lessonModel({ r: res.r, data: res.slice });
  assert.ok(m.sM != null && m.sB != null);
  assert.ok(Math.abs(m.sM - res.r.mix.m.sharpe) < 1e-12 && Math.abs(m.sB - res.r.bench.m.sharpe) < 1e-12);
});

// ---------- next step and "So what?" ----------
test("next step reads the result and always points to Plus", () => {
  const base = { bench: "SPY", mixSharpe: 0.4, benchSharpe: 0.6 };
  const behind = nextStep({ ...base, diff: -100 }), ahead = nextStep({ ...base, diff: 100 }), even = nextStep({ ...base, diff: 0 });
  assert.equal(behind.tone, "behind"); assert.match(behind.title, /trailed SPY/);
  assert.equal(ahead.tone, "ahead"); assert.match(ahead.body, /more risk/);
  assert.equal(even.tone, "even");
  for (const n of [behind, ahead, even]) assert.match(n.ask, /lowered risk.*Plus/);
  assert.match(nextStep({ ...base, diff: 100, mixSharpe: 0.9 }).body, /more for each unit of risk/);
});
test("So what compares the two ratios in one sentence", () => {
  assert.equal(soWhat("Mix", "SPY", 0.42, 0.57), "SPY earned more for every unit of bumpiness than Mix: 0.57 against 0.42.");
  assert.match(soWhat("Mix", "SPY", 0.8, 0.5), /^Mix earned more/);
  assert.match(soWhat("Mix", "SPY", null, 0.5), /cash rate/);
  assert.deepEqual([0.2, 0.7, 1.2, 2].map(sharpeBand), [0, 1, 2, 3]);
});
