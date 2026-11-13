// Saved portfolios, kept in this browser only (localStorage). Pure: the storage object is passed in, so tests use a fake.
// Versioned so a future account can import it. Nothing here touches the network.
export const STORE_KEY = "ufo-portfolios";
export const STORE_VERSION = 1;
const MAX_NAME = 60;
const MAX_ITEMS = 50;

const clean = (s) => String(s ?? "").replace(/[\u0000-\u001f]/g, " ").trim().slice(0, MAX_NAME);

function read(store) {
  try {
    const raw = JSON.parse(store.getItem(STORE_KEY) || "null");
    if (!raw || raw.version !== STORE_VERSION || !Array.isArray(raw.portfolios)) return { version: STORE_VERSION, portfolios: [] };
    return { version: STORE_VERSION, portfolios: raw.portfolios.filter(valid) };
  } catch { return { version: STORE_VERSION, portfolios: [] }; }
}

function valid(p) {
  return p && typeof p.id === "string" && typeof p.name === "string" && p.weights && typeof p.weights === "object"
    && Object.values(p.weights).every((w) => Number.isFinite(w) && w > 0);
}

function write(store, data) {
  store.setItem(STORE_KEY, JSON.stringify(data));
}

/** weights are percents by symbol; settings: {benchmark, years, strategy, initial, monthly}. */
export function makePortfolio({ name, weights, benchmark, years, strategy, initial, monthly }, now = new Date()) {
  const w = {};
  for (const [s, v] of Object.entries(weights || {})) if (Number.isFinite(v) && v > 0) w[String(s).toUpperCase()] = v;
  if (!Object.keys(w).length) throw new Error("Nothing to save: the mix has no holdings.");
  return {
    id: `p${now.getTime().toString(36)}${Math.random().toString(36).slice(2, 6)}`,
    name: clean(name) || "My mix", weights: w, benchmark: String(benchmark || "").toUpperCase(),
    years: Number(years) || 5, strategy: strategy || "hold", initial: Number(initial) || 0, monthly: Number(monthly) || 0,
    savedAt: now.toISOString(),
  };
}

export const listPortfolios = (store) => read(store).portfolios.sort((a, b) => b.savedAt.localeCompare(a.savedAt));

export function savePortfolio(store, input, now = new Date()) {
  const data = read(store);
  if (data.portfolios.length >= MAX_ITEMS) throw new Error(`You can keep up to ${MAX_ITEMS} saved mixes. Delete one first.`);
  const p = makePortfolio(input, now);
  data.portfolios.push(p);
  write(store, data);
  return p;
}

export function renamePortfolio(store, id, name) {
  const data = read(store);
  const p = data.portfolios.find((x) => x.id === id);
  if (!p) return false;
  p.name = clean(name) || p.name;
  write(store, data);
  return true;
}

export function deletePortfolio(store, id) {
  const data = read(store);
  const next = data.portfolios.filter((x) => x.id !== id);
  write(store, { ...data, portfolios: next });
  return next.length !== data.portfolios.length;
}

/** Remove everything this site keeps on the device (any key starting "ufo-"). Returns the keys removed. */
export function clearEverything(local, session = null) {
  const gone = [];
  for (const area of [local, session]) {
    if (!area) continue;
    const keys = [];
    for (let i = 0; i < area.length; i++) keys.push(area.key(i));
    for (const k of keys) if (k && k.startsWith("ufo-")) { area.removeItem(k); gone.push(k); }
  }
  return gone;
}

/** The whole saved object, for a future account import. */
export const exportAll = (store) => read(store);
