"""Parse a Fidelity "Positions" CSV export (Accounts > Positions > Download) into normalized holdings.
Port of fin-advisor's csv.mjs. Prices are as of the download, not Plaid's previous close.

Note: Fidelity's "Type" column is the account type (Cash/Margin), not the security type.
"""
from __future__ import annotations

import csv
import io
import re

COLS = {
    "account_number": ["accountnumber", "account", "acctnumber"],
    "account_name": ["accountname", "acctname"],
    "symbol": ["symbol", "ticker"],
    "description": ["description", "securitydescription", "name"],
    "quantity": ["quantity", "shares", "qty"],
    "price": ["lastprice", "price", "currentprice"],
    "value": ["currentvalue", "value", "marketvalue"],
    "cost_basis": ["costbasistotal", "costbasis"],
}
CASH_SYMBOLS = {"SPAXX", "FDRXX", "FZFXX", "FDLXX", "FCASH", "CORE", "SPRXX", "FZDXX"}


def _m(n: float) -> str:
    """Plain decimal for messages (no exponent / 6-digit truncation)."""
    return f"{n:.6f}".rstrip("0").rstrip(".")


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def parse_number(s: str | None) -> float | None:
    """'$1,234.50' -> 1234.5, '(12.00)' -> -12, '--', 'n/a', '' -> None"""
    t = (s or "").strip()
    if not t or re.fullmatch(r"(--|n/a|na|-)", t, re.I):
        return None
    neg = (t.startswith("(") and t.endswith(")")) or t.startswith("-")
    try:
        n = float(re.sub(r"[()$,%+\s-]", "", t))
    except ValueError:
        return None
    return -n if neg else n


def parse_fidelity_positions(text: str) -> tuple[list[dict], list[str]]:
    rows = list(csv.reader(io.StringIO(text.lstrip("﻿"), newline="")))
    header_idx = next((i for i, r in enumerate(rows)
                       if (n := [_norm(c) for c in r]) and "symbol" in n and ("quantity" in n or "shares" in n)
                       and any(x in COLS["value"] for x in n)), -1)
    if header_idx < 0:
        raise ValueError("Could not find a header row with Symbol, Quantity and Current Value columns. Is this a Fidelity Positions export?")
    header = [_norm(c) for c in rows[header_idx]]
    col = {k: next((i for i, h in enumerate(header) if h in names), -1) for k, names in COLS.items()}

    def get(r: list[str], k: str) -> str:
        return (r[col[k]] if 0 <= col[k] < len(r) else "").strip()

    holdings: list[dict] = []
    warnings: list[str] = []
    for r in rows[header_idx + 1:]:
        if all(not c.strip() for c in r):
            if holdings:
                break  # a blank line ends the table
            continue
        raw_symbol, acct = get(r, "symbol"), get(r, "account_number")
        if not raw_symbol or not acct:
            continue  # disclaimer/footer lines
        value = parse_number(get(r, "value"))
        if re.search("pending activity", raw_symbol, re.I):
            if value:
                warnings.append(f"Pending activity of ${_m(value)} in account ...{acct[-4:]} was ignored.")
            continue
        sym = raw_symbol.rstrip("*").upper()
        is_cash = raw_symbol.endswith("**") or sym in CASH_SYMBOLS
        quantity, price, val = parse_number(get(r, "quantity")), parse_number(get(r, "price")), value
        if is_cash:
            val = val if val is not None else quantity
            quantity, price = val, 1.0
        else:
            if val is None and quantity is not None and price is not None:
                val = quantity * price
            if price is None and quantity and val is not None:
                price = val / quantity
            if quantity is None and price and val is not None:
                quantity = val / price
        if val is None:
            warnings.append(f"Skipped {sym} (account ...{acct[-4:]}): no value.")
            continue
        holdings.append({
            "account": f"{get(r, 'account_name') or 'Account'} …{acct[-4:]}", "account_mask": acct[-4:],
            "symbol": "CASH" if is_cash else sym, "name": get(r, "description") or None, "is_cash": is_cash,
            "quantity": quantity, "price": price, "value": val, "cost_basis": parse_number(get(r, "cost_basis")),
        })
    if not holdings:
        raise ValueError("No positions found in the CSV.")
    return holdings, warnings
