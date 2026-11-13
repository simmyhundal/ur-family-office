// "How Sharpe works" as a list of steps (each step is a list of DOM nodes). Same words and arithmetic as before;
// the Learn page shows one step per card. The maths comes from calc.mjs.
import { sharpeSteps, blend5050, priceReturns } from "./calc.mjs";
import { el, svg, money, monthYear } from "./util.mjs";

const pm = (x, d = 2) => (x == null || Number.isNaN(x) ? "n/a" : (x * 100).toFixed(d) + "%");
const pp = (x, d = 2) => (x == null || Number.isNaN(x) ? "n/a" : (x >= 0 ? "+" : "") + (x * 100).toFixed(d) + "%");

export function lessonSteps({ r, data, mix, bench, monthly, name }) {
  const rets = r.mix.sim.returns, n = rets.length, dates = data.dates.slice(1);
  const P = (...kids) => el("p", {}, ...kids);
  const S = sharpeSteps(rets, data.rf), B = sharpeSteps(r.bench.sim.returns, data.rf);
  const steps = [];

  const k = n - 1, vals = r.mix.sim.values, flow = monthly > 0 ? monthly : 0;
  const startV = vals[k], endBefore = startV * (1 + rets[k]);
  const rows12 = rets.map((x, i) => i).slice(-12);
  steps.push({ title: "One return per month", body: [
    P("For each month, compare what the investments are worth at the end with what they were worth at the start. Money you add is not a return, so it is left out: the deposit lands after the month is measured."),
    P(`Worked example, ${monthYear(dates[k])} for ${name}:`),
    table(["", ""], [
      ["Value at the start of the month", money(startV)],
      ["Value at the end, before that month’s deposit", money(endBefore)],
      ["Deposit made at month-end (not a return)", money(flow)],
      ["Gain from the investments themselves", (endBefore - startV >= 0 ? "+" : "") + money(endBefore - startV)],
      ["Return for the month", pp(rets[k])],
    ], true),
    P(S ? "The last twelve months (the Sharpe ratio uses all " + n + "):" : "The last twelve months:"),
    table(S ? ["Month", "Return", "Cash (T-bill)", "Above cash"] : ["Month", "Return"],
      rows12.map((i) => S ? [monthYear(dates[i]), pp(rets[i]), pm(S.cash[i]), pp(S.excess[i])] : [monthYear(dates[i]), pp(rets[i])])),
  ] });

  if (!S) {
    steps.push({ title: "Why the rest needs a cash rate", body: [
      P("The remaining steps need a cash (T-bill) rate, and prices from your own CSV don’t carry one, so the Sharpe ratio is n/a here. Use the built-in prices to see all the steps.")] });
  } else {
    steps.push(
      { title: "Subtract what cash would have paid", body: [
        P(`Money could have sat in 3-month US Treasury bills, close to risk-free. Over these ${n} months that paid about ${pm(S.meanCash, 3)} a month (${pm(S.meanCash * 12)} a year). Only the return above that rewards you for taking risk, so each month’s return minus the T-bill rate is the excess return (last column of the table in step 1).`)] },
      { title: "Average the excess returns", body: [
        P(`Your average monthly excess return was ${pp(S.meanExcess, 3)}. Times 12 that is about ${pp(S.meanExcessAnnual)} a year.`),
        P(`Why times 12 and not compounded? Compounding, (1 + monthly)^12 − 1, is the right way to say what you earned in a year (${name} compounded to ${pp(S.compoundedAnnual)} a year here). The Sharpe ratio uses simple scaling instead, because volatility can only be scaled to a year by √12 when returns are added, not multiplied. Scaling the average by 12 and the volatility by √12 keeps both in the same units. This is the standard convention (Sharpe, 1994).`)] },
      { title: "Measure how bumpy the ride was", body: [
        P(`Volatility is the standard deviation of those monthly excess returns: roughly, how far a typical month lands from the average. Here it is ${pm(S.sd, 3)} a month. Good and bad months partly cancel, so the yearly figure scales by √12 (about 3.46): ${pm(S.sdAnnual)} a year.`),
        P(`Sanity check: ${S.within} of ${n} months landed within one standard deviation of the average (about 68% would be typical, here ${Math.round((S.within / n) * 100)}%).`)] },
      { title: "Divide", body: [
        P(el("b", {}, "Sharpe = average excess return ÷ volatility")),
        P(`${pp(S.meanExcessAnnual)} ÷ ${pm(S.sdAnnual)} = `, el("b", {}, S.sharpe == null ? "n/a" : S.sharpe.toFixed(2)),
          `. The code does the same sum in monthly units (${pp(S.meanExcess, 3)} ÷ ${pm(S.sd, 3)} × √12) and gets the same answer.` +
          (B && B.sharpe != null ? ` ${bench} over the same months: ${B.sharpe.toFixed(2)}.` : "")),
        P("Reading it: higher is better. Roughly, below 0.5 is modest, around 1 is good, above 1.5 is rare. It treats a surprise gain as “risk” just like a loss, and a short window can show almost anything.")] });
  }

  // Modern portfolio theory
  const w = Object.entries(mix).sort((a, b) => b[1] - a[1]).slice(0, 2);
  let div;
  if (w.length === 2) {
    const [fa, fb] = w.map(([s]) => s), m = blend5050(priceReturns(data.series[fa]), priceReturns(data.series[fb]));
    div = P(`Take two funds in the mix, ${fa} and ${fb}. Their volatilities are ${pm(m.volA, 1)} and ${pm(m.volB, 1)} a year, and their monthly returns have a correlation of ${m.corr.toFixed(2)} (1.0 would mean they always move together, 0 not at all). A 50/50 blend of the two has a volatility of `, el("b", {}, pm(m.volMix, 1)),
      `, against ${pm(m.volAvg, 1)} for the simple average of the two. That gap is the diversification benefit: ${m.volMix < m.volAvg - 1e-9 ? "less risk without giving up the average return." : "none here, because these two move almost in lockstep."}`);
  } else div = P("Add a second fund to the mix to see the diversification example.");
  steps.push(
    { title: "Mixing lowers risk", tag: "Portfolio theory", body: [P("In 1952 Harry Markowitz showed that what matters is not each investment on its own, but how they move together. Mixing lowers risk when things don’t move in lockstep."), div] },
    { title: "The efficient frontier", tag: "Portfolio theory", body: [P("Try every possible mix of a set of funds and plot each one’s risk and return. The upper-left edge of that cloud is the efficient frontier: for each level of risk, the best return any mix achieved. Mixes below the edge take risk without being paid for it.")] });
  if (S && S.sharpe != null) {
    steps.push({ title: "The Sharpe ratio is a slope", tag: "Portfolio theory", body: [
      P(`Put a point at zero risk and the T-bill return (${pm(S.meanCash * 12, 1)}). Draw a line from it to any portfolio: the steepness is that portfolio’s Sharpe ratio. ${name} has slope ${S.sharpe.toFixed(2)}${B && B.sharpe != null ? `; ${bench} has ${B.sharpe.toFixed(2)}` : ""}.`),
      slopeChart(S, B, name, bench)] });
  }
  steps.push({ title: "The best mix touches the frontier", tag: "Portfolio theory", body: [
    P("The steepest line that still reaches the frontier touches it at one mix: the maximum-Sharpe (tangency) portfolio. In practice the frontier is drawn from past returns, which shift, so the “best” mix is an estimate, not a promise."),
    el("p", { class: "muted small" }, "Information, not investment advice. Before taxes and trading costs; past results don’t predict future ones.")] });
  return steps;
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
