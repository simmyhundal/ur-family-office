// The page. All data stays in the browser: no network calls except loading the bundled demo prices.
import { compare, parsePricesCsv, sliceFor } from "./calc.mjs";

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
const monthYear = (iso) => new Date(iso + "T00:00:00").toLocaleDateString("en-US", { month: "short", year: "numeric" });

const state = { years: 5, data: null, labels: {}, demo: true, source: "", rows: [], presets: [], mixName: "Your mix" };
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
  state.data = { dates: d.dates, series: d.series };
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
function markCustom() { state.mixName = "Your mix"; $("preset").value = "custom"; }

function setup() {
  $("data-banner").textContent = state.demo
    ? "Demo data: invented funds, not real prices."
    : state.source || `Your file: ${symbols().length} funds.`;
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
    const r = compare({ prices: data.series, mix, benchmark: bench, initial, monthly, strategy: $("strategy").value });
    draw({ r, dates: data.dates, monthly, bench, limitedBy: data.limitedBy, years: state.years });
    drawOthers({ data, mix, others, initial, monthly, mixEnd: r.mix.m.endValue });
  } catch (e) {
    err.textContent = e.message;
    for (const id of ["verdict", "period-line", "chart-desc"]) $(id).textContent = "";
    for (const id of ["cards", "chart", "legend", "table-wrap", "benchmarks"]) $(id).replaceChildren();
  }
}

function card(kind, title, m) {
  const rows = [
    ["Gain", (m.gain >= 0 ? "+" : "") + money(m.gain)],
    ["Per year", m.annualReturn == null ? "n/a (under 12 mo)" : spct(m.annualReturn)],
    ["Ups and downs", m.volatility == null ? "n/a" : pct(m.volatility)],
    ["Worst fall", pct(m.maxDrawdown)],
  ];
  const dl = el("dl");
  for (const [k, v] of rows) dl.append(el("dt", {}, k), el("dd", {}, v));
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
  const head = el("tr", {}, ...["Benchmark", "Ends at", "Per year", `${state.mixName} vs it`].map((t) => el("th", { scope: "col" }, t)));
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
    state.data = { dates: parsed.dates, series: parsed.series };
    state.labels = {}; state.demo = false; state.source = ""; state.presets = []; state.mixName = "Your mix";
    const names = Object.keys(parsed.series);
    state.rows = names.slice(0, 2).map((s, i) => ({ sym: s, w: i ? 40 : 60 }));
    $("benchmark").value = names[0];
    setup();
  } catch (err) {
    $("error").textContent = err.message;
  }
});
$("reset-data").addEventListener("click", () => { $("csv").value = ""; load(); });

load().catch((e) => { $("error").textContent = "Could not load prices: " + e.message; });
