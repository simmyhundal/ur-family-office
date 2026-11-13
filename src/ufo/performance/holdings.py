"""What each account holds: fund, value and weight from the latest positions snapshot, grouped into coarse asset classes.

The classes come from a small editable local file (`.data/asset_classes.json`: {"VTI": "us_stock", ...}). Cash and
CD/T-bill CUSIPs classify themselves; any other ticker missing from the file is shown as "unclassified" rather than guessed.
Local only: these are exact holdings.
"""
from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel
from rich.console import Console
from rich.table import Table

from ufo.performance.ledger import is_fixed_income

CLASSES = {"us_stock": "US stock", "intl_stock": "International stock", "bonds": "Bonds", "cash": "Cash",
           "other": "Other", "unclassified": "Unclassified"}


class Holding(BaseModel):
    symbol: str
    name: str = ""
    value: float
    is_cash: bool = False


def classes_path(root: Path) -> Path:
    return root / ".data" / "asset_classes.json"


def load_classes(path: Path) -> dict[str, str]:
    """Ticker -> class key. A missing file is an empty mapping; a bad one raises ValueError in plain words."""
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"{path.name} is not valid JSON (line {e.lineno}).") from None
    if not isinstance(raw, dict):
        raise ValueError(f"{path.name} must map tickers to classes, like {{\"VTI\": \"us_stock\"}}.")
    out = {}
    for sym, cls in raw.items():
        if cls not in CLASSES or cls == "unclassified":
            raise ValueError(f"{path.name}: {sym} has class {cls!r}; use one of {', '.join(k for k in CLASSES if k != 'unclassified')}.")
        out[str(sym).strip().upper()] = cls
    return out


def classify(h: Holding, mapping: dict[str, str]) -> str:
    if h.is_cash:
        return "cash"
    sym = h.symbol.upper()
    if sym in mapping:
        return mapping[sym]
    return "bonds" if is_fixed_income(sym) else "unclassified"


def summarize(holdings: list[Holding], mapping: dict[str, str]) -> dict:
    """{"total", "rows": [{symbol, name, value, weight, cls}] largest first, "by_class": {class key: weight}}."""
    total = sum(h.value for h in holdings)
    rows = [{"symbol": h.symbol, "name": h.name, "value": round(h.value, 2), "weight": (h.value / total) if total else 0.0,
             "cls": classify(h, mapping)} for h in sorted(holdings, key=lambda h: -h.value)]
    by: dict[str, float] = {}
    for r in rows:
        by[r["cls"]] = by.get(r["cls"], 0.0) + r["weight"]
    return {"total": round(total, 2), "rows": rows, "by_class": by}


def print_holdings(runs, mapping: dict[str, str], console: Console | None = None) -> None:
    c = console or Console()
    shown = [r for r in runs if r.holdings]
    for r in shown:
        s = summarize(r.holdings, mapping)
        t = Table(title=f"{r.account.label}: holdings as of {r.holdings_as_of}", header_style="bold")
        for col, right in (("Fund", False), ("Class", False), ("Value", True), ("Weight", True)):
            t.add_column(col, justify="right" if right else "left")
        for row in s["rows"]:
            t.add_row(row["symbol"] + (f"  {row['name'][:28]}" if row["name"] else ""), CLASSES[row["cls"]],
                      f"${row['value']:,.0f}", f"{row['weight']:.1%}")
        c.print(t)
    if shown:
        keys = [k for k in CLASSES if any(summarize(r.holdings, mapping)["by_class"].get(k) for r in shown)]
        m = Table(title="Mix by asset class", header_style="bold")
        m.add_column("Account")
        for k in keys:
            m.add_column(CLASSES[k], justify="right")
        for r in shown:
            by = summarize(r.holdings, mapping)["by_class"]
            m.add_row(r.account.label, *[f"{by.get(k, 0):.0%}" if by.get(k) else "-" for k in keys])
        c.print(m)
        un = sorted({h.symbol for r in shown for h in r.holdings if classify(h, mapping) == "unclassified"})
        if un:
            c.print(f"[dim]- Unclassified (add to .data/asset_classes.json): {', '.join(un)}[/dim]")
