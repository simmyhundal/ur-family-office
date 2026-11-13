// "How Sharpe works" for a curious beginner: one idea per card, the one number that matters circled or highlighted.
// The maths comes from calc.mjs (same arithmetic as metrics()); the cards are DOM nodes built here.
import { sharpeSteps, blend5050, priceReturns } from "./calc.mjs";
import { el, svg, money, monthYear } from "./util.mjs";

const pm = (x, d = 2) => (x == null || Number.isNaN(x) ? "n/a" : (x * 100).toFixed(d) + "%");
const pp = (x, d = 2) => (x == null || Number.isNaN(x) ? "n/a" : (x >= 0 ? "+" : "") + (x * 100).toFixed(d) + "%");
const ratio = (x) => (x == null ? "n/a" : x.toFixed(2));
const P = (...kids) => el("p", {}, ...kids);
const mark = (t) => el("mark", {}, t);
const circ = (n) => el("span", { class: "circ", "aria-hidden": "true" }, String(n));
const note = (t) => el("span", { class: "note" }, t);
const focus = (t, label) => el("div", {}, el("span", { class: "focus-num", "aria-label": label ? `${label}: ${t}` : t }, t));

/** Where a Sharpe ratio sits on the usual rough scale (0..3). */
export const sharpeBand = (s) => (s == null ? -1 : s < 0.5 ? 0 : s < 1 ? 1 : s < 1.5 ? 2 : 3);

/** The one-sentence "So what?" comparing the two ratios. */
export function soWhat(name, bench, s, b) {
  if (s == null || b == null) return "Without a cash rate there is no Sharpe ratio to compare; the built-in prices have one.";
  if (Math.abs(s - b) < 0.005) return `${name} and ${bench} were paid the same for each bump along the way (${ratio(s)}).`;
  const [hi, lo, hs, ls] = s > b ? [name, bench, s, b] : [bench, name, b, s];
  return `${hi} earned more for every unit of bumpiness than ${lo}: ${ratio(hs)} against ${ratio(ls)}.`;
}

/** The numbers behind the cards (pure): the mix's and the benchmark's Sharpe steps, from the same result Try shows. */
export function lessonModel({ r, data }) {
  const S = sharpeSteps(r.mix.sim.returns, data.rf), B = sharpeSteps(r.bench.sim.returns, data.rf);
  return { S, B, sM: S?.sharpe ?? null, sB: B?.sharpe ?? null };
}

export function lessonSteps({ r, data, mix, bench, monthly, name }) {
  const rets = r.mix.sim.returns, n = rets.length, dates = data.dates.slice(1);
  const { S, B, sM, sB } = lessonModel({ r, data });
  const steps = [];

  // 0. The two numbers, and the question.
  steps.push({ title: "Two numbers from the Try page", tag: "Start here", body: [
    el("div", { class: "big-two" },
      el("div", { class: "m" }, el("span", { class: "lab" }, name), el("b", {}, ratio(sM)), el("span", { class: "muted small" }, "Sharpe ratio")),
      el("div", { class: "b" }, el("span", { class: "lab" }, bench), el("b", {}, ratio(sB)), el("span", { class: "muted small" }, "Sharpe ratio"))),
    el("p", { class: "huh" }, "What in the world is that?"),
    P("A score for ", mark("how much return you got for the bumps you sat through"), ". Higher is better. Five steps and you can work it out yourself."),
  ] });

  // 1. One month's return.
  const k = n - 1, vals = r.mix.sim.values, startV = vals[k], endBefore = startV * (1 + rets[k]);
  const last6 = Array.from({ length: Math.min(6, n) }, (_, i) => n - Math.min(6, n) + i);
  steps.push({ title: "Each month gets a return", tag: "Step 1", body: [
    P(circ(1), "Take one month, ", el("b", {}, monthYear(dates[k])), ": what it was worth at the start, and at the end."),
    table(["", ""], [["Start of the month", money(startV)], ["End, before any new deposit", money(endBefore)]], { plain: true }),
    focus(pp(rets[k]), "Return for the month"),
    note(monthly > 0 ? `the ${money(monthly)} deposit is not a return, so it is left out` : "that's the month's return"),
    table(["Month", "Return"], last6.map((i) => [monthYear(dates[i]), pp(rets[i])]), { pick: last6.length - 1 }),
    more(`All ${n} months`, S ? ["Month", "Return", "Cash", "Above cash"] : ["Month", "Return"],
      rets.map((x, i) => (S ? [monthYear(dates[i]), pp(x), pm(S.cash[i]), pp(S.excess[i])] : [monthYear(dates[i]), pp(x)]))),
  ] });

  if (!S) {
    steps.push({ title: "This step needs a cash rate", tag: "Step 2", body: [
      P("The next steps subtract what cash paid. Prices from your own file don’t carry a cash rate, so the Sharpe ratio is n/a here. Use the built-in prices to see every step.")] });
  } else {
    // 2. Subtract cash.
    steps.push({ title: "Take away what cash paid", tag: "Step 2", body: [
      P(circ(2), "You could have left the money in ", mark("3-month Treasury bills"), ", close to risk-free. Only the return ", el("i", {}, "above"), " that pays you for taking risk."),
      el("div", { class: "formula" }, el("span", {}, pp(rets[k])), el("span", { class: "op" }, "−"), el("span", {}, pm(S.cash[k], 2)),
        el("span", { class: "op" }, "="), el("span", { class: "focus-num" }, pp(S.excess[k]))),
      note(`${monthYear(dates[k])}: return, minus cash, = above cash`),
    ] });
    // 3. Average, yearly.
    steps.push({ title: "Average it, then make it yearly", tag: "Step 3", body: [
      P(circ(3), `Do that for all ${n} months and take the average: ${pp(S.meanExcess, 3)} a month.`),
      el("div", { class: "formula" }, el("span", {}, pp(S.meanExcess, 3)), el("span", { class: "op" }, "× 12 ="), el("span", { class: "focus-num" }, pp(S.meanExcessAnnual))),
      note("the reward: return above cash, per year"),
    ] });
    // 4. Volatility.
    steps.push({ title: "Measure the bumps", tag: "Step 4", body: [
      P(circ(4), "How far does a typical month land from that average? That spread is ", mark("volatility"), ". Scaled to a year (× √12):"),
      focus(pm(S.sdAnnual), "Volatility a year"),
      note(`${S.within} of ${n} months landed within one bump of the average`),
    ] });
    // 5. Divide.
    steps.push({ title: "Divide reward by bumps", tag: "Step 5", body: [
      P(circ(5), mark("Sharpe = reward ÷ bumps"), "."),
      el("div", { class: "formula" }, el("span", {}, pp(S.meanExcessAnnual)), el("span", { class: "op" }, "÷"), el("span", {}, pm(S.sdAnnual)),
        el("span", { class: "op" }, "="), el("span", { class: "focus-num" }, ratio(sM))),
      scale(sM),
      note("rough guide; a short history can show almost anything"),
    ] });
  }

  // So what?
  steps.push({ title: "So what?", tag: "The point", end: true, body: [
    el("p", { class: "sowhat" }, soWhat(name, bench, sM, sB)),
    P("Return alone hides the ride. Sharpe puts the ride back in."),
    el("p", { class: "muted small" }, "Information, not investment advice. Before taxes and costs; past results don’t predict future ones."),
  ] });

  // Going further (optional): portfolio theory, on the same mix.
  const w = Object.entries(mix).sort((a, b) => b[1] - a[1]).slice(0, 2);
  const extra = [];
  if (w.length === 2) {
    const [fa, fb] = w.map(([s]) => s), m = blend5050(priceReturns(data.series[fa]), priceReturns(data.series[fb]));
    extra.push({ title: "Mixing lowers the bumps", tag: "Going further", body: [
      P(`${fa} alone bumps ${pm(m.volA, 1)} a year; ${fb} ${pm(m.volB, 1)}. Half and half:`),
      focus(pm(m.volMix, 1), "Volatility of a 50/50 blend"),
      note(m.volMix < m.volAvg - 1e-9 ? `less than the ${pm(m.volAvg, 1)} average, because they don’t move in lockstep` : "about the average: these two move almost together"),
      P("That is Harry Markowitz’s 1952 idea: what matters is how investments move together."),
    ] });
  }
  if (S && sM != null) extra.push({ title: "Sharpe is a slope", tag: "Going further", body: [
    P("Draw a line from cash to each portfolio. ", mark("Steeper line, higher Sharpe"), "."), slopeChart(S, B, name, bench)] });
  extra.push({ title: "The best mix is an estimate", tag: "Going further", body: [
    P("Try every mix of some funds and plot risk against return. The steepest line from cash that still touches that cloud marks the ", mark("maximum-Sharpe mix"), "."),
    note("drawn from past returns, which shift: an estimate, not a promise"),
    el("p", { class: "muted small" }, "Information, not investment advice."),
  ] });
  return { steps, extra };
}

function table(head, rows, { plain = false, pick = -1 } = {}) {
  const t = el("table", { class: "lesson-table" });
  if (!plain) t.append(el("thead", {}, el("tr", {}, ...head.map((h) => el("th", { scope: "col" }, h)))));
  t.append(el("tbody", {}, ...rows.map((rw, ri) => el("tr", ri === pick ? { class: "pick" } : {},
    ...rw.map((c, i) => el(i || !plain ? "td" : "th", plain && !i ? { scope: "row" } : {}, c))))));
  return el("div", { class: "table-scroll" }, t);
}
function more(label, head, rows) {
  return el("details", { class: "lesson-more" }, el("summary", {}, label), table(head, rows));
}
function scale(s) {
  const at = sharpeBand(s);
  return el("div", { class: "scale", role: "img", "aria-label": "Rough scale: below 0.5 modest, 0.5 to 1 fair, 1 to 1.5 good, above 1.5 rare" },
    ...["< 0.5 modest", "0.5–1 fair", "1–1.5 good", "> 1.5 rare"].map((t, i) => el("span", i === at ? { class: "on" } : {}, t)));
}

function slopeChart(S, B, name, bench) {
  const pts = [{ n: name, x: S.sdAnnual, y: S.meanExcessAnnual + S.meanCash * 12, c: "var(--mix)" }];
  if (B && B.sharpe != null) pts.push({ n: bench, x: B.sdAnnual, y: B.meanExcessAnnual + B.meanCash * 12, c: "var(--bench)" });
  const cash = S.meanCash * 12, W = 560, H = 220, L = 52, Rr = 190, T = 14, Bt = 34;
  const xm = Math.max(...pts.map((p) => p.x)) * 1.15, ys = [cash, ...pts.map((p) => p.y)];
  const y0 = Math.min(0, ...ys), y1 = Math.max(...ys) * 1.15 || 0.1;
  const X = (v) => L + (v / xm) * (W - L - Rr), Y = (v) => T + (1 - (v - y0) / (y1 - y0)) * (H - T - Bt);
  const root = svg("svg", { viewBox: `0 0 ${W} ${H}`, class: "slope", role: "img", "aria-label": `Risk against return: lines from cash to ${pts.map((p) => p.n).join(" and ")}; steeper means a higher Sharpe ratio.` });
  root.append(svg("line", { class: "grid", x1: L, x2: W - Rr, y1: Y(0), y2: Y(0) }), svg("line", { class: "grid", x1: L, x2: L, y1: T, y2: H - Bt }));
  const text = (x, y, t, a = {}) => { const e = svg("text", { class: "axis-text", x, y, ...a }); e.textContent = t; return e; };
  root.append(text(L + (W - L - Rr) / 2, H - 6, "Bumps (yearly volatility) →", { "text-anchor": "middle" }), text(L - 6, Y(cash) + 4, pm(cash, 1), { "text-anchor": "end" }));
  root.append(svg("circle", { cx: X(0), cy: Y(cash), r: 4, fill: "var(--ink-2)" }), text(L + 8, Y(cash) + 18, "Cash (T-bills)"));
  for (const p of pts) {
    root.append(svg("line", { x1: X(0), y1: Y(cash), x2: X(p.x), y2: Y(p.y), stroke: p.c, "stroke-width": 2 }), svg("circle", { cx: X(p.x), cy: Y(p.y), r: 5, fill: p.c }),
      text(X(p.x) + 9, Y(p.y) + 4, `${p.n} (${((p.y - cash) / p.x).toFixed(2)})`, { "font-weight": 600 }));
  }
  return el("figure", { class: "chart-fig" }, root, el("figcaption", { class: "muted small" }, "Return a year (up) against bumps (right). Slope of each line = Sharpe ratio."));
}
