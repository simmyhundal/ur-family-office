// Tests for the save / upload / share modules. Every holding and number is invented.   Run: node --test tests/site/
import test from "node:test";
import assert from "node:assert/strict";
import { FIDELITY_POSITIONS_INVENTED } from "./fixtures/fidelity-positions-invented.mjs";
import { encodeShare, decodeShare, shareUrl, cardContent } from "../../site/js/share.mjs";
import { parsePositions, parseNumber, csvRows, TEMPLATE_CSV } from "../../site/js/positions.mjs";
import { savePortfolio, listPortfolios, renamePortfolio, deletePortfolio, clearEverything, STORE_KEY } from "../../site/js/portfolios.mjs";

const KNOWN = ["VTI", "BND", "VXUS", "SPY", "QQQ"];

class FakeStore {
  constructor() { this.m = new Map(); }
  get length() { return this.m.size; }
  key(i) { return [...this.m.keys()][i] ?? null; }
  getItem(k) { return this.m.has(k) ? this.m.get(k) : null; }
  setItem(k, v) { this.m.set(k, String(v)); }
  removeItem(k) { this.m.delete(k); }
}

// ---------- share ----------
test("share link round trip keeps weights, benchmark, window, style", () => {
  const s = { weights: { VTI: 60, BND: 25.5, VXUS: 14.5 }, benchmark: "spy", years: 10, strategy: "annual" };
  const back = decodeShare("?" + encodeShare(s));
  assert.deepEqual(back, { weights: { VTI: 60, BND: 25.5, VXUS: 14.5 }, benchmark: "SPY", years: 10, strategy: "annual" });
});

test("share link normalizes weights to percent and has no dollar figures or deposit fields", () => {
  const url = shareUrl("https://example.test/try/", { weights: { VTI: 3000, BND: 1000 }, benchmark: "SPY", years: 5, strategy: "hold", initial: 12345, monthly: 678 });
  const q = decodeURIComponent(url.split("?")[1]);
  assert.equal(decodeShare(url.split("?")[1]).weights.VTI, 75);
  assert.ok(!q.includes("$"));
  assert.ok(!/12345|678|initial|monthly|deposit/i.test(url));
  assert.deepEqual([...new URLSearchParams(url.split("?")[1]).keys()].sort(), ["b", "mix", "s", "y"]);
});

test("decode drops junk and refuses empty links", () => {
  assert.equal(decodeShare(""), null);
  assert.equal(decodeShare("?mix=%3Cscript%3E~50"), null);
  const d = decodeShare("?mix=VTI~50_BAD!~10_BND~-5&b=<x>&y=7&s=nope");
  assert.deepEqual(d, { weights: { VTI: 50 }, benchmark: null, years: 5, strategy: "hold" });
  assert.throws(() => encodeShare({ weights: {}, benchmark: "SPY" }));
});

test("card content is percentages and ratios only", () => {
  const c = cardContent({ weights: { VTI: 60, BND: 40 }, benchmark: "SPY", years: 5, mixAnnual: 0.081, benchAnnual: 0.095, mixSharpe: 0.9, benchSharpe: 1.1 });
  const all = Object.values(c).join(" | ");
  assert.ok(!all.includes("$"));
  assert.match(all, /VTI 60%/);
  assert.match(all, /\+8\.1% a year/);
  assert.match(all, /Sharpe 0\.90 vs 1\.10/);
});

// ---------- positions ----------
test("numbers: commas, dollar signs, parentheses, blanks", () => {
  assert.equal(parseNumber("$1,234.50"), 1234.5);
  assert.equal(parseNumber("(12.00)"), -12);
  assert.equal(parseNumber("--"), null);
  assert.equal(parseNumber(""), null);
  assert.equal(parseNumber("abc"), null);
});

test("csvRows handles quoted commas and escaped quotes", () => {
  assert.deepEqual(csvRows('a,"1,000","say ""hi"""\nb,2,3\n'), [["a", "1,000", 'say "hi"'], ["b", "2", "3"]]);
});

test("template file becomes weights", () => {
  const r = parsePositions(TEMPLATE_CSV, KNOWN);
  assert.equal(r.format, "template");
  assert.deepEqual(r.weights, { VTI: 60, VXUS: 20, BND: 20 });
  assert.deepEqual(r.unknown, []);
});

test("template: commas in numbers, cash line, totals row, lowercase symbols", () => {
  const csv = 'Symbol,Value\nvti,"$7,500.00"\nbnd,"2,500"\nCash,"1,000"\nTotal,"11,000"\n';
  const r = parsePositions(csv, KNOWN);
  assert.deepEqual(r.weights, { VTI: 75, BND: 25 });
  assert.equal(r.cashSkipped, true);
  assert.match(r.notes.join(" "), /Cash/);
});

test("invented Fidelity export: accounts combined, cash, pending, unknown and footer lines handled", () => {
  const text = FIDELITY_POSITIONS_INVENTED;
  const r = parsePositions(text, KNOWN);
  assert.equal(r.format, "fidelity");
  // VTI 5000 + 2500 = 7500, BND 2100 -> 78.1 / 21.9
  assert.deepEqual(r.weights, { VTI: 78.1, BND: 21.9 });
  assert.equal(Object.values(r.weights).reduce((a, b) => a + b, 0).toFixed(1), "100.0");
  assert.deepEqual(r.unknown, [{ symbol: "ZZZQ", value: 400 }]);
  assert.equal(r.cashSkipped, true);
  assert.match(r.notes.join(" "), /ZZZQ/);
});

test("errors: wrong file and nothing priced", () => {
  assert.throws(() => parsePositions("a,b\n1,2\n", KNOWN), /Symbol/);
  assert.throws(() => parsePositions("symbol,value\nZZZQ,100\n", KNOWN), /None of the 1 symbols/);
  assert.throws(() => parsePositions("symbol,value\nVTI,0\n", KNOWN), /No positions/);
});

test("positions parser makes no network calls", () => {
  const orig = globalThis.fetch;
  let called = false;
  globalThis.fetch = () => { called = true; throw new Error("network"); };
  try { parsePositions(TEMPLATE_CSV, KNOWN); } finally { globalThis.fetch = orig; }
  assert.equal(called, false);
});

// ---------- saved portfolios ----------
const base = { name: "Core", weights: { VTI: 60, BND: 40 }, benchmark: "SPY", years: 5, strategy: "hold", initial: 2000, monthly: 500 };

test("save, list, rename, delete; shape is versioned", () => {
  const st = new FakeStore();
  const a = savePortfolio(st, base, new Date("2026-01-01T00:00:00Z"));
  savePortfolio(st, { ...base, name: "Later" }, new Date("2026-02-01T00:00:00Z"));
  assert.equal(JSON.parse(st.getItem(STORE_KEY)).version, 1);
  assert.deepEqual(listPortfolios(st).map((p) => p.name), ["Later", "Core"]);
  assert.ok(renamePortfolio(st, a.id, "  Renamed  "));
  assert.equal(listPortfolios(st).find((p) => p.id === a.id).name, "Renamed");
  assert.ok(deletePortfolio(st, a.id));
  assert.equal(listPortfolios(st).length, 1);
});

test("saved data survives a fresh read and bad data is ignored", () => {
  const st = new FakeStore();
  savePortfolio(st, base);
  assert.equal(listPortfolios(st)[0].weights.VTI, 60);
  st.setItem(STORE_KEY, "{not json");
  assert.deepEqual(listPortfolios(st), []);
  st.setItem(STORE_KEY, JSON.stringify({ version: 99, portfolios: [{}] }));
  assert.deepEqual(listPortfolios(st), []);
  assert.throws(() => savePortfolio(st, { ...base, weights: {} }), /Nothing to save/);
});

test("clear everything removes only this site's keys, in both storages", () => {
  const local = new FakeStore(), session = new FakeStore();
  savePortfolio(local, base);
  session.setItem("ufo-mix", "{}");
  local.setItem("other-site", "keep");
  const gone = clearEverything(local, session);
  assert.deepEqual(gone.sort(), ["ufo-mix", STORE_KEY].sort());
  assert.equal(local.getItem("other-site"), "keep");
  assert.deepEqual(listPortfolios(local), []);
});
