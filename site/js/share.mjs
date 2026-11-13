// Share links and the share card. A link carries weights (percent), benchmark, window and style: never dollars or deposits.
const SYM = /^[A-Z0-9][A-Z0-9.\-]{0,9}$/;
const YEARS = [1, 3, 5, 10, 99];
const STYLES = ["hold", "annual", "monthly"];

/** -> query string like "mix=VTI-60.VXUS-40&b=SPY&y=5&s=hold" (no leading ?). Weights are rounded to 0.1. */
export function encodeShare({ weights, benchmark, years = 5, strategy = "hold" }) {
  const total = Object.values(weights).filter((w) => w > 0).reduce((a, b) => a + b, 0);
  if (!(total > 0)) throw new Error("Nothing to share: the mix has no holdings.");
  const parts = Object.entries(weights).filter(([, w]) => w > 0).map(([s, w]) => `${s.toUpperCase()}~${Math.round((w / total) * 1000) / 10}`);
  const p = new URLSearchParams({ mix: parts.join("_"), b: String(benchmark).toUpperCase(), y: String(years), s: strategy });
  return p.toString();
}

/** Parse and validate; unknown or malformed pieces are dropped. Returns null when there is no usable mix. */
export function decodeShare(search) {
  const p = new URLSearchParams(String(search).replace(/^\?/, ""));
  const mix = p.get("mix");
  if (!mix) return null;
  const weights = {};
  for (const part of mix.split("_").slice(0, 40)) {
    const [s, w] = part.split("~");
    const n = Number(w);
    if (SYM.test(s || "") && Number.isFinite(n) && n > 0 && n <= 100) weights[s] = n;
  }
  if (!Object.keys(weights).length) return null;
  const b = (p.get("b") || "").toUpperCase();
  const years = Number(p.get("y"));
  const strategy = p.get("s");
  return { weights, benchmark: SYM.test(b) ? b : null, years: YEARS.includes(years) ? years : 5, strategy: STYLES.includes(strategy) ? strategy : "hold" };
}

export const shareUrl = (base, share) => `${base}?${encodeShare(share)}`;

const win = (y) => (y >= 99 ? "all available history" : `last ${y} year${y === 1 ? "" : "s"}`);

/** The words on the share card: percentages and ratios only. Pure, so a test can scan it for dollar figures. */
export function cardContent({ weights, benchmark, years, mixAnnual, benchAnnual, mixSharpe, benchSharpe }) {
  const total = Object.values(weights).reduce((a, b) => a + b, 0);
  const top = Object.entries(weights).sort((a, b) => b[1] - a[1]).slice(0, 5).map(([s, w]) => `${s} ${Math.round((w / total) * 100)}%`);
  const pc = (x) => (x == null ? "n/a" : `${x >= 0 ? "+" : ""}${(x * 100).toFixed(1)}%`);
  const sh = (x) => (x == null ? "n/a" : x.toFixed(2));
  return {
    title: "My mix vs " + benchmark,
    mixLine: `${pc(mixAnnual)} a year`, benchLine: `${benchmark}: ${pc(benchAnnual)} a year`,
    sharpeLine: `Sharpe ${sh(mixSharpe)} vs ${sh(benchSharpe)}`,
    mixText: top.join("  ·  "), window: win(years),
    foot: "Information, not advice. Before taxes and costs. Made with UFO.",
  };
}
