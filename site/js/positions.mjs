// Turn a positions CSV into mix weights. Two layouts: the simple template (symbol,value) and the Fidelity positions export.
// Pure text in, plain object out; nothing is sent anywhere.
export const TEMPLATE_CSV = "symbol,value\nVTI,6000\nVXUS,2000\nBND,2000\n";
const CASH = new Set(["SPAXX", "FDRXX", "FZFXX", "FDLXX", "FCASH", "CORE", "SPRXX", "FZDXX", "CASH", "USD"]);
const norm = (s) => String(s ?? "").toLowerCase().replace(/[^a-z0-9]/g, "");

/** Split CSV text into rows, honoring quotes (commas and newlines inside quotes, "" escapes). */
export function csvRows(text) {
  const rows = [];
  let row = [], cell = "", q = false;
  const src = String(text).replace(/^﻿/, "");
  for (let i = 0; i < src.length; i++) {
    const c = src[i];
    if (q) {
      if (c === '"') { if (src[i + 1] === '"') { cell += '"'; i++; } else q = false; } else cell += c;
    } else if (c === '"') q = true;
    else if (c === ",") { row.push(cell); cell = ""; }
    else if (c === "\n" || c === "\r") {
      if (c === "\r" && src[i + 1] === "\n") i++;
      row.push(cell); rows.push(row); row = []; cell = "";
    } else cell += c;
  }
  if (cell !== "" || row.length) { row.push(cell); rows.push(row); }
  return rows;
}

/** '$1,234.50' -> 1234.5; '(12.00)' or '-12' -> -12; '--', 'n/a', '' -> null */
export function parseNumber(s) {
  const t = String(s ?? "").trim();
  if (!t || /^(--|n\/a|na|-)$/i.test(t)) return null;
  const neg = (t.startsWith("(") && t.endsWith(")")) || t.startsWith("-");
  const n = Number(t.replace(/[()$,%+\s-]/g, ""));
  return Number.isFinite(n) && /\d/.test(t) ? (neg ? -n : n) : null;
}

const TOTAL = /^(account\s+)?totals?\b|^grand total/i;
const isSymbol = (s) => /^[A-Z0-9][A-Z0-9.\-]{0,9}$/.test(s);

/**
 * @param text CSV text
 * @param known symbols that have prices (array or Set)
 * @returns {format, weights (percent, sums to 100), unknown [{symbol, value}], cashSkipped, notes[]}
 */
export function parsePositions(text, known) {
  const knownSet = new Set(known);
  const rows = csvRows(text);
  const hi = rows.findIndex((r) => { const n = r.map(norm); return n.includes("symbol") && (n.includes("currentvalue") || n.includes("value") || n.includes("marketvalue")); });
  if (hi < 0) throw new Error("Couldn't find a Symbol and a Value (or Current Value) column. Use the template, or Fidelity's Positions download.");
  const head = rows[hi].map(norm);
  const at = (...names) => head.findIndex((h) => names.includes(h));
  const iSym = at("symbol", "ticker"), iVal = at("currentvalue", "marketvalue", "value");
  const iAcct = at("accountnumber", "account", "acctnumber");
  const fidelity = head.includes("currentvalue") && (head.includes("quantity") || head.includes("lastprice"));
  const notes = [];
  const total = new Map();
  let cashSkipped = false, seen = false;
  for (const r of rows.slice(hi + 1)) {
    if (r.every((c) => !c.trim())) { if (seen && fidelity) break; continue; } // a blank line ends the Fidelity table
    const raw = (r[iSym] ?? "").trim();
    if (!raw || TOTAL.test(raw) || TOTAL.test((r[0] ?? "").trim())) continue; // totals and footer lines
    if (fidelity && iAcct >= 0 && !(r[iAcct] ?? "").trim()) continue; // disclaimer lines
    if (/pending activity/i.test(raw)) continue;
    const isCashStar = raw.endsWith("**");
    const sym = raw.replace(/\*+$/, "").toUpperCase();
    const val = parseNumber(r[iVal]);
    seen = true;
    if (isCashStar || CASH.has(sym)) { if (val) cashSkipped = true; continue; }
    if (val == null || val <= 0) continue;
    if (!isSymbol(sym)) { notes.push(`Skipped a line that doesn't look like a ticker.`); continue; }
    total.set(sym, (total.get(sym) || 0) + val);
  }
  const unknown = [], kept = [];
  for (const [symbol, value] of total) (knownSet.has(symbol) ? kept : unknown).push({ symbol, value });
  const sum = kept.reduce((s, x) => s + x.value, 0);
  const weights = {};
  if (sum > 0) {
    kept.sort((a, b) => b.value - a.value);
    let used = 0;
    kept.forEach((x, i) => {
      const w = i === kept.length - 1 ? Math.round((100 - used) * 10) / 10 : Math.round((x.value / sum) * 1000) / 10;
      used += w;
      if (w > 0) weights[x.symbol] = w;
    });
  }
  if (cashSkipped) notes.push("Cash and money-market lines were left out; the weights are of the rest.");
  if (unknown.length) notes.push(`No prices for ${unknown.map((u) => u.symbol).join(", ")}; left out.`);
  if (!Object.keys(weights).length) throw new Error(unknown.length ? `None of the ${unknown.length} symbols have prices here (${unknown.map((u) => u.symbol).join(", ")}).` : "No positions with a value were found.");
  return { format: fidelity ? "fidelity" : "template", weights, unknown, cashSkipped, notes };
}
