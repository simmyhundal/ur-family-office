// The page. All data stays in the browser: no network calls except loading the bundled demo prices.
import { compare, parsePricesCsv, sliceFor, sharpeSteps, blend5050, priceReturns } from "./calc.mjs";

const $ = (id) => document.getElementById(id);
const el = (tag, attrs = {}, ...kids) => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) (k === "class" ? (n.className = v) : n.setAttribute(k, v));
  for (const kid of kids) n.append(kid);
  return n;
};
const NS = "http://www.w3.org/2000/svg";
const svg = (tag, attrs = {}) => {
  const n = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  return n;
};
const money = (x) => (x < 0 ? "-" : "") + "$" + Math.round(Math.abs(x)).toLocaleString("en-US");
const pct = (x, d = 1) => (x == null || Number.isNaN(x) ? "n/a" : (x * 100).toFixed(d) + "%");
const spct = (x, d = 1) => (x == null ? "n/a" : (x >= 0 ? "+" : "") + (x * 100).toFixed(d) + "%");
const TIPS = {
  gain: "Ending value minus the money you put in, before taxes.",
  year: "How fast the investments grew each year, as if $1 had stayed in the whole time. Your deposits and timing don't flatter it. Needs 12 months of history.",
  ups: "How much the monthly returns swing, shown as a yearly figure (volatility). Higher means a bumpier ride.",
  fall: "The biggest drop from a previous high point, before it recovered (maximum drawdown).",
  sharpe: "Return above a safe cash rate (3-month Treasury bills) for each unit of ups and downs. Higher is better: below 0.5 is weak, around 1 is good, above 2 is rare. Needs 12 months of history.",
  ends: "What the money would be worth on the last date, before taxes.",
};
const tip = (label, key) => el("span", { class: "tip", tabindex: "0", "data-tip": TIPS[key], "aria-description": TIPS[key] }, label);
const monthYear = (iso) => new Date(iso + "T00:00:00").toLocaleDateString("en-US", { month: "short", year: "numeric" });

const state = { years: 5, data: null, labels: {}, demo: true, source: "", rows: [], presets: [], mixName: "Your mix", sample: false };
const OTHER = ["SPY", "VTI", "QQQ", "IWM", "AGG"]; // shown in the "other benchmarks" table when the data has them

async function getJson(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(url + " " + res.status);
  return res.json();
}

async function load() {
  let d, demo = false;
  if (globalThis.UFO_DATA) d = globalThis.UFO_DATA; // set by scripts/build_single_page.py (one-file copy of the site)
  else try { d = await getJson("data/prices.json"); } catch { d = await getJson("data/demo-prices.json"); demo = true; }
  state.data = { dates: d.dates, series: d.series, rf: d.rf ?? null }; // rf: cash rate in % a year (list per date, or one number)
  state.labels = d.labels || {};
  state.demo = demo;
  state.source = d.asOf ? `Prices to ${d.asOf}.` : "";
  const has = (x) => x in d.series;
  let presets = [];
  if (!demo) { try { presets = globalThis.UFO_PRESETS || await getJson("data/presets.json"); } catch { /* no presets is fine */ } }
  state.presets = presets.filter((p) => Object.keys(p.weights).every(has)); // only mixes whose funds all have prices
  state.rows = demo ? [{ sym: "DEMOUS", w: 60 }, { sym: "DEMOBD", w: 30 }, { sym: "DEMOGD", w: 10 }]
    : state.presets.length ? rowsOf(state.presets[0]) : starter();
  state.mixName = state.presets.length && !demo ? state.presets[0].name : "Your mix";
  $("benchmark").value = has("SPY") ? "SPY" : Object.keys(d.series)[0];
  setup();
}

const symbols = () => Object.keys(state.data.series);
const rowsOf = (p) => Object.entries(p.weights).map(([sym, w]) => ({ sym, w }));
const starter = () => (["VTI", "BND"].every((x) => x in state.data.series) ? [{ sym: "VTI", w: 60 }, { sym: "BND", w: 40 }]
  : symbols().slice(0, 2).map((sym, i) => ({ sym, w: i ? 40 : 60 })));
function markCustom() { state.sample = false; state.mixName = "Your mix"; $("preset").value = "custom"; }

function setup() {
  $("data-banner").textContent = state.demo
    ? "Demo data: invented funds, not real prices."
    : state.source || `Your file: ${symbols().length} funds.`;
  $("sample-note").hidden = !state.sample;
  $("reset-data").hidden = state.demo && !$("csv").value;
  $("tickers").replaceChildren(...symbols().map((s) => el("option", { value: s }, state.labels[s] || "")));
  state.rows = state.rows.filter((r) => symbols().includes(r.sym));
  if (!state.rows.length) state.rows = [{ sym: symbols()[0], w: 100 }];
  const pre = $("preset");
  pre.replaceChildren(...state.presets.map((p, i) => el("option", { value: String(i) }, p.name)), el("option", { value: "custom" }, "Your own"));
  pre.value = state.mixName === "Your mix" ? "custom" : String(state.presets.findIndex((p) => p.name === state.mixName));
  pre.closest("label").hidden = !state.presets.length;
  renderRows();
  render();
}

function renderRows() {
  const box = $("rows");
  box.replaceChildren();
  state.rows.forEach((row, i) => {
    const sel = el("input", { list: "tickers", autocomplete: "off", spellcheck: "false", value: row.sym, "aria-label": `Fund ${i + 1}`, placeholder: "Ticker" });
    sel.addEventListener("input", () => { row.sym = sel.value.trim().toUpperCase(); markCustom(); render(); });
    const w = el("input", { type: "number", min: "0", max: "100", step: "1", value: String(row.w), "aria-label": `Weight ${i + 1}, percent` });
    w.addEventListener("input", () => { row.w = Number(w.value); markCustom(); render(); });
    const rm = el("button", { type: "button", class: "rm", "aria-label": `Remove fund ${i + 1}` }, "×");
    rm.addEventListener("click", () => { state.rows.splice(i, 1); markCustom(); renderRows(); render(); });
    box.append(el("div", { class: "mix-row" }, sel, w, rm));
  });
}

function mixWeights() {
  const out = {};
  for (const r of state.rows) if (r.w > 0) out[r.sym] = (out[r.sym] || 0) + r.w;
  return out;
}

let last = null;

function render() {
  const err = $("error");
  err.textContent = "";
  const total = state.rows.reduce((s, r) => s + (r.w > 0 ? r.w : 0), 0);
  $("weight-note").textContent = total === 100 ? "" : `Adds up to ${Math.round(total * 10) / 10}%, scaled to 100%.`;
  try {
    const initial = Number($("initial").value);
    const monthly = Number($("monthly").value) || 0;
    if (!(initial > 0)) throw new Error("Enter a starting amount above zero.");
    const mix = mixWeights();
    const bench = $("benchmark").value.trim().toUpperCase();
    const unknown = [...Object.keys(mix), bench].filter((x) => !(x in state.data.series));
    if (unknown.length) throw new Error(`No prices for ${unknown.join(", ")}. Pick from the list, or use your own CSV.`);
    const others = OTHER.filter((x) => x in state.data.series);
    const needed = [...new Set([...Object.keys(mix), bench, ...others])];
    const data = sliceFor(state.data, needed, state.years);
    if (data.dates.length < 3) throw new Error("Not enough months of prices to compare.");
    const r = compare({ prices: data.series, mix, benchmark: bench, initial, monthly, strategy: $("strategy").value, rf: data.rf });
    draw({ r, dates: data.dates, monthly, bench, limitedBy: data.limitedBy, years: state.years });
    drawOthers({ data, mix, others, initial, monthly, mixEnd: r.mix.m.endValue });
    drawLesson({ r, data, mix, bench, monthly });
  } catch (e) {
    err.textContent = e.message;
    for (const id of ["verdict", "period-line", "chart-desc"]) $(id).textContent = "";
    for (const id of ["cards", "chart", "legend", "table-wrap", "benchmarks", "lesson-body"]) $(id).replaceChildren();
  }
}

function card(kind, title, m) {
  const rows = [
    ["Gain", (m.gain >= 0 ? "+" : "") + money(m.gain)],
    ["Per year", m.annualReturn == null ? "n/a" : spct(m.annualReturn)],
    ["Ups and downs", m.volatility == null ? "n/a" : pct(m.volatility)],
    ["Worst fall", pct(m.maxDrawdown)],
    ["Sharpe ratio", m.sharpe == null ? "n/a" : m.sharpe.toFixed(2)],
  ];
  const keys = ["gain", "year", "ups", "fall", "sharpe"];
  const dl = el("dl");
  rows.forEach(([k, v], i) => dl.append(el("dt", {}, tip(k, keys[i])), el("dd", {}, v)));
  return el("div", { class: `card ${kind}` }, el("h3", {}, title), el("div", { class: "hero" }, money(m.endValue)), dl);
}

function draw({ r, dates, monthly, bench, limitedBy, years }) {
  const { mix, bench: b } = r;
  $("period-line").textContent = `${monthYear(dates[0])} to ${monthYear(dates.at(-1))}.` +
    (limitedBy ? ` Starts when ${limitedBy} does.` : years < 99 && mix.m.months < years * 12 ? " That is all the history there is." : "") + ` Put in ${money(mix.m.putIn)}.`;
  const mixName = state.mixName, benchName = bench;
  $("cards").replaceChildren(card("mix", mixName, mix.m), card("bench", benchName, b.m));
  const diff = mix.m.endValue - b.m.endValue;
  $("verdict").textContent = diff === 0 ? "Same result."
    : `${mixName} finished ${money(Math.abs(diff))} ${diff > 0 ? "ahead of" : "behind"} ${bench}. Worst fall: ${pct(Math.abs(mix.m.maxDrawdown))} vs ${pct(Math.abs(b.m.maxDrawdown))}.`;
  drawChart({ dates, series: [{ name: mixName, key: "mix", color: "var(--mix)", v: mix.sim.values }, { name: benchName, key: "bench", color: "var(--bench)", v: b.sim.values }], put: monthly > 0 ? mix.sim.contributed : null });
  drawTable(dates, mixName, benchName, mix.sim.values, b.sim.values, monthly > 0 ? mix.sim.contributed : null);
}

// ---------- chart ----------
let lastChart = null;
const PL = 64, PR = 16, PT = 20, PB = 28;

function niceTicks(max) {
  const raw = max / 4, mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((k) => k * mag).find((s) => s >= raw);
  const out = [];
  for (let v = 0; ; v += step) { out.push(v); if (v >= max) break; }
  return out;
}

function drawOthers({ data, mix, others, initial, monthly, mixEnd }) {
  const box = $("benchmarks");
  if (others.length < 2) { box.replaceChildren(); return; }
  const rows = others.map((b) => {
    const m = compare({ prices: data.series, mix, benchmark: b, initial, monthly, strategy: $("strategy").value }).bench.m;
    const d = mixEnd - m.endValue;
    return el("tr", {}, el("td", {}, b), el("td", {}, money(m.endValue)), el("td", {}, m.annualReturn == null ? "n/a" : spct(m.annualReturn)), el("td", {}, (d >= 0 ? "+" : "-") + money(Math.abs(d))));
  });
  const head = el("tr", {}, ...["Benchmark", "Ends at", "Per year", `${state.mixName} vs it`].map((t, i) => el("th", { scope: "col" }, i === 1 ? tip(t, "ends") : i === 2 ? tip(t, "year") : t)));
  box.replaceChildren(el("h3", {}, "Other benchmarks"), el("table", {}, el("thead", {}, head), el("tbody", {}, ...rows)));
}

function drawChart({ dates, series, put }) {
  lastChart = { dates, series, put };
  const W = Math.max(300, Math.round($("chart").clientWidth || 760)), H = W < 520 ? 240 : 300; // drawn at real size so text stays readable
  const all = series.flatMap((s) => s.v).concat(put || []);
  const ticks = niceTicks(Math.max(...all) * 1.05);
  const top = ticks.at(-1), n = dates.length;
  const x = (i) => PL + (i / (n - 1)) * (W - PL - PR);
  const y = (v) => PT + (1 - v / top) * (H - PT - PB);
  const root = svg("svg", { viewBox: `0 0 ${W} ${H}`, "aria-hidden": "true", focusable: "false" });
  for (const t of ticks) {
    root.append(svg("line", { class: "grid", x1: PL, x2: W - PR, y1: y(t), y2: y(t) }));
    const lab = svg("text", { class: "axis-text", x: PL - 8, y: y(t) + 4, "text-anchor": "end" });
    lab.textContent = money(t);
    root.append(lab);
  }
  for (let i = 0; i < n; i += W < 520 ? 24 : 12) {
    const lab = svg("text", { class: "axis-text", x: x(i), y: H - 8, "text-anchor": i === 0 ? "start" : x(i) > W - PR - 40 ? "end" : "middle" });
    lab.textContent = monthYear(dates[i]);
    root.append(lab);
  }
  const path = (v) => v.map((val, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(val).toFixed(1)}`).join("");
  if (put) root.append(svg("path", { d: path(put), fill: "none", stroke: "var(--put)", "stroke-width": 2, "stroke-dasharray": "5 4" }));
  for (const s of series) root.append(svg("path", { d: path(s.v), fill: "none", stroke: s.color, "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }));
  // direct end labels (selective): the final value of each line
  const ends = series.map((s) => ({ s, yy: y(s.v.at(-1)) })).sort((a, b) => a.yy - b.yy);
  if (ends.length === 2 && ends[1].yy - ends[0].yy < 14) ends[1].yy = ends[0].yy + 14;
  for (const { s, yy } of W < 520 ? [] : ends) { // narrow screens: the cards already show these
    const t = svg("text", { x: W - PR - 4, y: yy - 6, "text-anchor": "end", "font-size": 12, "font-weight": 600, fill: "var(--ink)" });
    t.textContent = money(s.v.at(-1));
    root.append(t);
  }
  const cross = svg("line", { y1: PT, y2: H - PB, stroke: "var(--ink-2)", "stroke-width": 1, visibility: "hidden" });
  const dots = series.map((s) => svg("circle", { r: 5, fill: s.color, stroke: "var(--surface)", "stroke-width": 2, visibility: "hidden" }));
  root.append(cross, ...dots);
  const tip = el("div", { class: "tooltip", hidden: "" });
  const chart = $("chart");
  chart.replaceChildren(root, tip);

  let idx = n - 1;
  const show = (i) => {
    idx = Math.max(0, Math.min(n - 1, i));
    const px = x(idx);
    cross.setAttribute("x1", px); cross.setAttribute("x2", px); cross.setAttribute("visibility", "visible");
    series.forEach((s, k) => { dots[k].setAttribute("cx", px); dots[k].setAttribute("cy", y(s.v[idx])); dots[k].setAttribute("visibility", "visible"); });
    tip.replaceChildren(el("b", {}, monthYear(dates[idx])),
      ...series.map((s) => el("div", {}, el("span", { class: "k", style: `background:${s.color}` }), `${s.name}: ${money(s.v[idx])}`)),
      ...(put ? [el("div", {}, el("span", { class: "k", style: "background:var(--put)" }), `Put in: ${money(put[idx])}`)] : []));
    tip.hidden = false;
    const box = chart.getBoundingClientRect(), scale = box.width / W; // 1 unless the page was resized since the draw
    const left = px * scale + 12;
    tip.style.left = (left + tip.offsetWidth > box.width ? px * scale - tip.offsetWidth - 12 : left) + "px";
    tip.style.top = Math.round(box.width * (H / W) * 0.55) + "px"; // lower part of the plot: the lines stay visible
  };
  const hide = () => { cross.setAttribute("visibility", "hidden"); dots.forEach((d) => d.setAttribute("visibility", "hidden")); tip.hidden = true; };
  chart.onpointermove = (e) => { const b = chart.getBoundingClientRect(); show(Math.round(((e.clientX - b.left) / b.width * W - PL) / (W - PL - PR) * (n - 1))); };
  chart.onpointerleave = hide;
  chart.onfocus = () => show(idx);
  chart.onblur = hide;
  chart.onkeydown = (e) => {
    const step = { ArrowLeft: -1, ArrowRight: 1, PageDown: -12, PageUp: 12 }[e.key];
    if (e.key === "Home") { e.preventDefault(); show(0); } else if (e.key === "End") { e.preventDefault(); show(n - 1); }
    else if (step) { e.preventDefault(); show(idx + step); }
  };

  $("legend").replaceChildren(
    ...series.map((s) => el("span", {}, el("i", { style: `background:${s.color}` }), s.name)),
    ...(put ? [el("span", {}, el("i", { style: "background:var(--put)" }), "Put in")] : []));
  const a = series[0], b = series[1];
  $("chart-desc").textContent = `${state.mixName} goes from ${money(a.v[0])} to ${money(a.v.at(-1))}; the benchmark from ${money(b.v[0])} to ${money(b.v.at(-1))}. Arrow keys step through months.`;
}

function drawTable(dates, an, bn, a, b, put) {
  const head = ["Month", an, bn, ...(put ? ["Put in"] : [])];
  const table = el("table", {}, el("thead", {}, el("tr", {}, ...head.map((h) => el("th", { scope: "col" }, h)))));
  const body = el("tbody");
  dates.forEach((d, i) => body.append(el("tr", {}, el("td", {}, monthYear(d)), el("td", {}, money(a[i])), el("td", {}, money(b[i])), ...(put ? [el("td", {}, money(put[i]))] : []))));
  table.append(body);
  $("table-wrap").replaceChildren(el("div", { class: "table-scroll" }, table));
}

// ---------- sample portfolio ----------
// An invented person with invented deposits; the prices are the real bundled ones (or the demo set when running on demo data).
const SAMPLE = {
  real: { weights: { VTI: 50, VXUS: 20, BND: 20, QQQ: 10 } },
  demo: { weights: { DEMOUS: 60, DEMOBD: 30, DEMOGD: 10 } },
  initial: 2000, monthly: 500,
};
function loadSample() {
  const pick = SAMPLE.real.weights && Object.keys(SAMPLE.real.weights).every((x) => x in state.data.series) ? SAMPLE.real : SAMPLE.demo;
  if (!Object.keys(pick.weights).every((x) => x in state.data.series)) { $("error").textContent = "The sample needs the built-in prices; click “Back to built-in prices” first."; return; }
  state.rows = rowsOf(pick); state.mixName = "Sample MBA student"; state.sample = true;
  $("initial").value = SAMPLE.initial; $("monthly").value = SAMPLE.monthly; $("strategy").value = "hold";
  state.years = 5;
  document.querySelectorAll(".seg button").forEach((o) => o.setAttribute("aria-pressed", String(o.dataset.years === "5")));
  setup();
  $("preset").value = "custom";
  $("lesson").open = true;
}

// ---------- How Sharpe works ----------
const pm = (x, d = 2) => (x == null || Number.isNaN(x) ? "n/a" : (x * 100).toFixed(d) + "%");
const pp = (x, d = 2) => (x == null || Number.isNaN(x) ? "n/a" : (x >= 0 ? "+" : "") + (x * 100).toFixed(d) + "%");

function drawLesson({ r, data, mix, bench, monthly }) {
  const body = $("lesson-body");
  const name = state.mixName, rets = r.mix.sim.returns, n = rets.length, dates = data.dates.slice(1);
  const P = (...kids) => el("p", {}, ...kids);
  const H = (t) => el("h3", {}, t);
  const out = [];
  const rf = data.rf;
  const S = sharpeSteps(rets, rf), B = sharpeSteps(r.bench.sim.returns, rf);

  // Step 1: one return per month
  const k = n - 1, vals = r.mix.sim.values, flow = monthly > 0 ? monthly : 0;
  const startV = vals[k], endBefore = startV * (1 + rets[k]); // last month runs from vals[k] to vals[k+1]
  out.push(H("Step 1: one return per month"),
    P("For each month, compare what the investments are worth at the end with what they were worth at the start. Money you add is not a return, so it is left out: the deposit lands after the month is measured."),
    P(`Worked example, ${monthYear(dates[k])} for ${name}:`),
    table(["", ""], [
      ["Value at the start of the month", money(startV)],
      ["Value at the end, before that month’s deposit", money(endBefore)],
      ["Deposit made at month-end (not a return)", money(flow)],
      ["Gain from the investments themselves", (endBefore - startV >= 0 ? "+" : "") + money(endBefore - startV)],
      ["Return for the month", pp(rets[k])],
    ], true));
  const rows12 = rets.map((x, i) => i).slice(-12);
  out.push(P(S ? "The last twelve months (the Sharpe ratio uses all " + n + "):" : "The last twelve months:"),
    table(S ? ["Month", "Return", "Cash (T-bill)", "Above cash"] : ["Month", "Return"],
      rows12.map((i) => S ? [monthYear(dates[i]), pp(rets[i]), pm(S.cash[i]), pp(S.excess[i])] : [monthYear(dates[i]), pp(rets[i])])));

  if (!S) {
    out.push(P("The remaining steps need a cash (T-bill) rate, and prices from your own CSV don’t carry one, so the Sharpe ratio is n/a here. Use the built-in prices to see all the steps."));
  } else {
    out.push(
      H("Step 2: subtract what cash would have paid"),
      P(`Money could have sat in 3-month US Treasury bills, close to risk-free. Over these ${n} months that paid about ${pm(S.meanCash, 3)} a month (${pm(S.meanCash * 12)} a year). Only the return above that rewards you for taking risk, so each month’s return minus the T-bill rate is the excess return (last column above).`),
      H("Step 3: average the excess returns"),
      P(`Your average monthly excess return was ${pp(S.meanExcess, 3)}. Times 12 that is about ${pp(S.meanExcessAnnual)} a year.`),
      P(`Why times 12 and not compounded? Compounding, (1 + monthly)^12 − 1, is the right way to say what you earned in a year (${name} compounded to ${pp(S.compoundedAnnual)} a year here). The Sharpe ratio uses simple scaling instead, because volatility can only be scaled to a year by √12 when returns are added, not multiplied. Scaling the average by 12 and the volatility by √12 keeps both in the same units. This is the standard convention (Sharpe, 1994).`),
      H("Step 4: measure how bumpy the ride was"),
      P(`Volatility is the standard deviation of those monthly excess returns: roughly, how far a typical month lands from the average. Here it is ${pm(S.sd, 3)} a month. Good and bad months partly cancel, so the yearly figure scales by √12 (about 3.46): ${pm(S.sdAnnual)} a year.`),
      P(`Sanity check: ${S.within} of ${n} months landed within one standard deviation of the average (about 68% would be typical, here ${Math.round((S.within / n) * 100)}%).`),
      H("Step 5: divide"),
      P(el("b", {}, "Sharpe = average excess return ÷ volatility")),
      P(`${pp(S.meanExcessAnnual)} ÷ ${pm(S.sdAnnual)} = `, el("b", {}, S.sharpe == null ? "n/a" : S.sharpe.toFixed(2)),
        `. The code does the same sum in monthly units (${pp(S.meanExcess, 3)} ÷ ${pm(S.sd, 3)} × √12) and gets the same answer.` +
        (B && B.sharpe != null ? ` ${bench} over the same months: ${B.sharpe.toFixed(2)}.` : "")),
      P("Reading it: higher is better. Roughly, below 0.5 is modest, around 1 is good, above 1.5 is rare. It treats a surprise gain as “risk” just like a loss, and a short window can show almost anything."));
  }

  // MPT
  out.push(el("h3", {}, "How this connects to modern portfolio theory"),
    P("In 1952 Harry Markowitz showed that what matters is not each investment on its own, but how they move together."));
  const w = Object.entries(mix).sort((a, b) => b[1] - a[1]).slice(0, 2);
  if (w.length === 2) {
    const [fa, fb] = w.map(([s]) => s), ra = priceReturns(data.series[fa]), rb = priceReturns(data.series[fb]);
    const m = blend5050(ra, rb);
    out.push(P(el("b", {}, "1. Mixing lowers risk when things don’t move in lockstep. "),
      `Take two funds in the mix, ${fa} and ${fb}. Their volatilities are ${pm(m.volA, 1)} and ${pm(m.volB, 1)} a year, and their monthly returns have a correlation of ${m.corr.toFixed(2)} (1.0 would mean they always move together, 0 not at all). A 50/50 blend of the two has a volatility of `, el("b", {}, pm(m.volMix, 1)),
      `, against ${pm(m.volAvg, 1)} for the simple average of the two. That gap is the diversification benefit: ${m.volMix < m.volAvg - 1e-9 ? "less risk without giving up the average return." : "none here, because these two move almost in lockstep."}`));
  } else out.push(P("Add a second fund to the mix to see the diversification example."));
  out.push(P(el("b", {}, "2. The efficient frontier. "), "Try every possible mix of a set of funds and plot each one’s risk and return. The upper-left edge of that cloud is the efficient frontier: for each level of risk, the best return any mix achieved. Mixes below the edge take risk without being paid for it."));
  if (S && S.sharpe != null) {
    out.push(P(el("b", {}, "3. The Sharpe ratio is a slope. "), `Put a point at zero risk and the T-bill return (${pm(S.meanCash * 12, 1)}). Draw a line from it to any portfolio: the steepness is that portfolio’s Sharpe ratio. ${name} has slope ${S.sharpe.toFixed(2)}${B && B.sharpe != null ? `; ${bench} has ${B.sharpe.toFixed(2)}` : ""}.`),
      slopeChart(S, B, name, bench));
  }
  out.push(P(el("b", {}, "4. The best mix touches the frontier. "), "The steepest line that still reaches the frontier touches it at one mix: the maximum-Sharpe (tangency) portfolio. In practice the frontier is drawn from past returns, which shift, so the “best” mix is an estimate, not a promise."),
    el("p", { class: "muted small" }, "Information, not investment advice. Before taxes and trading costs; past results don’t predict future ones."));
  body.replaceChildren(...out);
}

function table(head, rows, plain = false) {
  const t = el("table", { class: "lesson-table" });
  if (!plain) t.append(el("thead", {}, el("tr", {}, ...head.map((h) => el("th", { scope: "col" }, h)))));
  t.append(el("tbody", {}, ...rows.map((rw) => el("tr", {}, ...rw.map((c, i) => el(i || !plain ? "td" : "th", plain && !i ? { scope: "row" } : {}, c))))));
  return el("div", { class: "table-scroll" }, t);
}

function slopeChart(S, B, name, bench) {
  const pts = [{ n: name, x: S.sdAnnual, y: S.meanExcessAnnual + S.meanCash * 12, c: "var(--mix)" }];
  if (B && B.sharpe != null) pts.push({ n: bench, x: B.sdAnnual, y: B.meanExcessAnnual + B.meanCash * 12, c: "var(--bench)" });
  const cash = S.meanCash * 12, W = 520, H = 220, L = 52, Rr = 90, T = 14, Bt = 34;
  const xm = Math.max(...pts.map((p) => p.x)) * 1.15, ys = [cash, ...pts.map((p) => p.y)];
  const y0 = Math.min(0, ...ys), y1 = Math.max(...ys) * 1.15 || 0.1;
  const X = (v) => L + (v / xm) * (W - L - Rr), Y = (v) => T + (1 - (v - y0) / (y1 - y0)) * (H - T - Bt);
  const root = svg("svg", { viewBox: `0 0 ${W} ${H}`, class: "slope", role: "img", "aria-label": `Risk against return: lines from cash to ${pts.map((p) => p.n).join(" and ")}; steeper means a higher Sharpe ratio.` });
  root.append(svg("line", { class: "grid", x1: L, x2: W - Rr, y1: Y(0), y2: Y(0) }), svg("line", { class: "grid", x1: L, x2: L, y1: T, y2: H - Bt }));
  const text = (x, y, t, a = {}) => { const e = svg("text", { class: "axis-text", x, y, ...a }); e.textContent = t; return e; };
  root.append(text(L + (W - L - Rr) / 2, H - 6, "Ups and downs (yearly volatility) →", { "text-anchor": "middle" }), text(L - 6, Y(cash) + 4, pm(cash, 1), { "text-anchor": "end" }));
  root.append(svg("circle", { cx: X(0), cy: Y(cash), r: 4, fill: "var(--ink-2)" }), text(L + 8, Y(cash) - 8, "Cash (T-bills)"));
  for (const p of pts) {
    root.append(svg("line", { x1: X(0), y1: Y(cash), x2: X(p.x), y2: Y(p.y), stroke: p.c, "stroke-width": 2 }), svg("circle", { cx: X(p.x), cy: Y(p.y), r: 5, fill: p.c }),
      text(X(p.x) + 9, Y(p.y) + 4, `${p.n} (${((p.y - cash) / p.x).toFixed(2)})`, { "font-weight": 600 }));
  }
  return el("figure", { class: "chart-fig" }, root, el("figcaption", { class: "muted small" }, "Return per year (up) against ups and downs (right). Slope of each line = Sharpe ratio."));
}

// ---------- events ----------
let resizeTimer = null, lastWidth = 0;
new ResizeObserver(() => {
  const w = $("chart").clientWidth;
  if (!lastChart || !w || w === lastWidth) return;
  lastWidth = w;
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => drawChart(lastChart), 100);
}).observe($("chart"));
$("preset").addEventListener("change", () => {
  const p = state.presets[Number($("preset").value)];
  state.rows = p ? rowsOf(p) : starter();
  state.mixName = p ? p.name : "Your mix";
  renderRows(); render();
});
$("add-row").addEventListener("click", () => {
  const used = new Set(state.rows.map((r) => r.sym));
  state.rows.push({ sym: symbols().find((s) => !used.has(s)) || symbols()[0], w: 10 });
  markCustom(); renderRows(); render();
});
for (const id of ["benchmark", "strategy", "initial", "monthly"]) $(id).addEventListener("input", render);
document.querySelectorAll(".seg button").forEach((b) => b.addEventListener("click", () => {
  state.years = Number(b.dataset.years);
  document.querySelectorAll(".seg button").forEach((o) => o.setAttribute("aria-pressed", String(o === b)));
  render();
}));
$("toggle-table").addEventListener("click", () => {
  const open = $("table-wrap").hidden;
  $("table-wrap").hidden = !open;
  $("toggle-table").setAttribute("aria-expanded", String(open));
  $("toggle-table").textContent = open ? "Hide table" : "Show table";
});
$("csv").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  try {
    const parsed = parsePricesCsv(await file.text());
    if (parsed.dates.length < 13) throw new Error("Need at least 13 months of prices that every fund shares.");
    state.data = { dates: parsed.dates, series: parsed.series, rf: null }; // no cash rate in a CSV, so no Sharpe
    state.labels = {}; state.demo = false; state.source = ""; state.presets = []; state.mixName = "Your mix";
    const names = Object.keys(parsed.series);
    state.rows = names.slice(0, 2).map((s, i) => ({ sym: s, w: i ? 40 : 60 }));
    $("benchmark").value = names[0];
    setup();
  } catch (err) {
    $("error").textContent = err.message;
  }
});
$("sample").addEventListener("click", loadSample);
$("reset-data").addEventListener("click", () => { $("csv").value = ""; load(); });

load().catch((e) => { $("error").textContent = "Could not load prices: " + e.message; });
