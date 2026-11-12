// The page. All data stays in the browser: no network calls except loading the bundled demo prices.
import { compare, parsePricesCsv, window as lastYears } from "./calc.mjs";

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
const num = (x) => (x == null ? "n/a" : x.toFixed(2));
const monthYear = (iso) => new Date(iso + "T00:00:00").toLocaleDateString("en-US", { month: "short", year: "numeric" });

const state = { data: null, labels: {}, rf: 3.5, demo: true, rows: [] };

async function loadDemo() {
  const res = await fetch("data/demo-prices.json");
  const d = await res.json();
  state.data = { dates: d.dates, series: d.series };
  state.labels = d.labels;
  state.rf = d.rf;
  state.demo = true;
  state.rows = [{ sym: "DEMOUS", w: 60 }, { sym: "DEMOBD", w: 30 }, { sym: "DEMOGD", w: 10 }];
  $("benchmark").dataset.pending = "DEMOUS";
  setup();
}

function symbols() { return Object.keys(state.data.series); }
const labelOf = (s) => (state.labels[s] ? `${s}: ${state.labels[s]}` : s);

function setup() {
  $("data-banner").textContent = state.demo
    ? "Demo data: the funds and prices below are invented, not real. Load your own prices file further down for a real comparison."
    : `Your prices file: ${symbols().length} funds, ${monthYear(state.data.dates[0])} to ${monthYear(state.data.dates.at(-1))}. It stays in your browser.`;
  $("reset-data").hidden = state.demo;
  const bench = $("benchmark");
  const keep = bench.dataset.pending || bench.value;
  bench.replaceChildren(...symbols().map((s) => el("option", { value: s }, labelOf(s))));
  bench.value = symbols().includes(keep) ? keep : symbols()[0];
  delete bench.dataset.pending;
  state.rows = state.rows.filter((r) => symbols().includes(r.sym));
  if (!state.rows.length) state.rows = [{ sym: symbols()[0], w: 100 }];
  renderRows();
  render();
}

function renderRows() {
  const box = $("rows");
  box.replaceChildren();
  state.rows.forEach((row, i) => {
    const sel = el("select", { "aria-label": `Fund ${i + 1}` }, ...symbols().map((s) => el("option", { value: s }, labelOf(s))));
    sel.value = row.sym;
    sel.addEventListener("change", () => { row.sym = sel.value; render(); });
    const w = el("input", { type: "number", min: "0", max: "100", step: "1", value: String(row.w), "aria-label": `Weight ${i + 1}, percent` });
    w.addEventListener("input", () => { row.w = Number(w.value); render(); });
    const rm = el("button", { type: "button", class: "rm", "aria-label": `Remove fund ${i + 1}` }, "×");
    rm.addEventListener("click", () => { state.rows.splice(i, 1); renderRows(); render(); });
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
  $("weight-note").textContent = total === 100 ? "Weights add up to 100%." : `Weights add up to ${Math.round(total * 10) / 10}%; they are scaled to 100%.`;
  try {
    const years = Number($("years").value);
    const data = lastYears(state.data, years);
    const initial = Number($("initial").value);
    const monthly = Number($("monthly").value) || 0;
    if (!(initial > 0)) throw new Error("Enter a starting amount above zero.");
    if (data.dates.length < 3) throw new Error("This prices file has too few months to compare.");
    const mix = mixWeights();
    const r = compare({ prices: data.series, mix, benchmark: $("benchmark").value, initial, monthly, strategy: $("strategy").value, rfAnnualPercent: state.rf });
    last = { r, dates: data.dates, monthly, years };
    draw(last);
  } catch (e) {
    err.textContent = e.message;
    $("verdict").textContent = ""; $("cards").replaceChildren(); $("chart").replaceChildren(); $("legend").replaceChildren(); $("table-wrap").replaceChildren();
    $("period-line").textContent = ""; $("chart-desc").textContent = "";
  }
}

function card(kind, title, m) {
  const rows = [
    ["Money put in", money(m.putIn)], ["Gain", (m.gain >= 0 ? "+" : "") + money(m.gain)],
    ["Total return", spct(m.totalReturn)], ["Return per year", m.annualReturn == null ? "needs 12 months" : spct(m.annualReturn)],
    ["Ups and downs", m.volatility == null ? "needs 12 months" : pct(m.volatility)], ["Worst fall", pct(m.maxDrawdown)],
    ["Sharpe ratio", m.sharpe == null ? "n/a" : num(m.sharpe)],
  ];
  const dl = el("dl");
  for (const [k, v] of rows) dl.append(el("dt", {}, k), el("dd", {}, v));
  return el("div", { class: `card ${kind}` }, el("h3", {}, title), el("div", { class: "hero" }, money(m.endValue)), el("div", { class: "sub" }, "worth at the end"), dl);
}

function draw({ r, dates, monthly, years }) {
  const { mix, bench } = r;
  $("period-line").textContent = `${monthYear(dates[0])} to ${monthYear(dates.at(-1))} (${mix.m.months} months). Same start, same deposits, same way of managing.`;
  const mixName = "Your mix", benchName = $("benchmark").value + " (benchmark)";
  $("cards").replaceChildren(card("mix", mixName, mix.m), card("bench", benchName, bench.m));
  const diff = mix.m.endValue - bench.m.endValue;
  const fall = (m) => pct(Math.abs(m.maxDrawdown));
  const deeper = mix.m.maxDrawdown < bench.m.maxDrawdown ? "deeper" : mix.m.maxDrawdown > bench.m.maxDrawdown ? "shallower" : "the same";
  $("verdict").textContent = diff === 0 ? "Your mix and the benchmark ended in the same place."
    : `Your mix ended ${money(Math.abs(diff))} ${diff > 0 ? "ahead of" : "behind"} the benchmark (${spct(mix.m.endValue / bench.m.endValue - 1)} on the end value). ` +
      `Its worst fall was ${fall(mix.m)}, against ${fall(bench.m)} for the benchmark (${deeper}).`;
  drawChart({ dates, series: [{ name: mixName, key: "mix", color: "var(--mix)", v: mix.sim.values }, { name: benchName, key: "bench", color: "var(--bench)", v: bench.sim.values }], put: monthly > 0 ? mix.sim.contributed : null });
  drawTable(dates, mixName, benchName, mix.sim.values, bench.sim.values, monthly > 0 ? mix.sim.contributed : null);
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
      ...(put ? [el("div", {}, el("span", { class: "k", style: "background:var(--put)" }), `Money put in: ${money(put[idx])}`)] : []));
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
    ...(put ? [el("span", {}, el("i", { style: "background:var(--put)" }), "Money put in")] : []));
  const a = series[0], b = series[1];
  $("chart-desc").textContent = `Line chart. Your mix goes from ${money(a.v[0])} to ${money(a.v.at(-1))}; the benchmark goes from ${money(b.v[0])} to ${money(b.v.at(-1))}. Use the arrow keys on the chart to step through the months, or show the table.`;
}

function drawTable(dates, an, bn, a, b, put) {
  const head = ["Month", an, bn, ...(put ? ["Money put in"] : [])];
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
$("add-row").addEventListener("click", () => {
  const used = new Set(state.rows.map((r) => r.sym));
  state.rows.push({ sym: symbols().find((s) => !used.has(s)) || symbols()[0], w: 10 });
  renderRows(); render();
});
for (const id of ["benchmark", "years", "strategy", "initial", "monthly"]) $(id).addEventListener("input", render);
$("toggle-table").addEventListener("click", () => {
  const open = $("table-wrap").hidden;
  $("table-wrap").hidden = !open;
  $("toggle-table").setAttribute("aria-expanded", String(open));
  $("toggle-table").textContent = open ? "Hide the table" : "Show as a table";
});
$("csv").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  try {
    const parsed = parsePricesCsv(await file.text());
    if (parsed.dates.length < 13) throw new Error("Need at least 13 month-ends of prices that every fund shares.");
    state.data = { dates: parsed.dates, series: parsed.series };
    state.labels = {}; state.demo = false;
    state.rows = Object.keys(parsed.series).slice(0, 2).map((s, i) => ({ sym: s, w: i ? 40 : 60 }));
    $("benchmark").dataset.pending = Object.keys(parsed.series)[0];
    setup();
  } catch (err) {
    $("error").textContent = err.message;
  }
});
$("reset-data").addEventListener("click", () => { $("csv").value = ""; loadDemo(); });

loadDemo().catch((e) => { $("error").textContent = "Could not load the demo prices: " + e.message; });
