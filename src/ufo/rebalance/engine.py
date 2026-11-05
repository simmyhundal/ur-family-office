"""Withdrawal + rebalance planning. Port of fin-advisor's rebalance.mjs and trades.mjs.

Positions are dicts: {symbol, quantity, price, value, is_cash}. Cash is the symbol 'CASH'.

Modes:
  sell_only : sell down to targets; cash is only touched if CASH is listed in the targets.
  buy_only  : the withdrawal must be covered by cash; leftover cash (above the CASH target, default 0%)
              is spent on under-target positions in proportion to how far under each is. Nothing is sold.
  full      : trade every listed symbol to its target value; net cash out equals the withdrawal.
  auto      : buy_only if cash covers the withdrawal, otherwise use all cash and sell the rest.
Model after the "Redistribution" sheet: desired = target% x (balance - withdrawal); sell = current - desired.
"""
from __future__ import annotations

import math

EPS = 1e-9


def _m(n: float) -> str:
    """Plain decimal for messages (no exponent / 6-digit truncation)."""
    return f"{n:.6f}".rstrip("0").rstrip(".")


def round2(n: float) -> float:
    return math.floor(n * 100 + 0.5) / 100  # JS Math.round semantics (half up), not banker's rounding


def round6(n: float) -> float:
    return math.floor(n * 1e6 + 0.5) / 1e6


def aggregate_by_symbol(holdings: list[dict]) -> list[dict]:
    """Merge rows with the same symbol (one ETF in several accounts); all cash becomes 'CASH'."""
    by: dict[str, dict] = {}
    for h in holdings:
        cash = bool(h.get("is_cash"))
        sym = "CASH" if cash else h["symbol"]
        cur = by.setdefault(sym, {"symbol": sym, "quantity": 0.0, "value": 0.0, "price": 1.0 if cash else h["price"], "is_cash": cash})
        cur["quantity"] += h["value"] if cash else h["quantity"]
        cur["value"] += h["value"]
    return list(by.values())


# ---------------------------------------------------------------- sell-only


def plan_withdrawal(positions: list[dict], withdrawal: float, targets: dict | None = None, whole_shares: bool = False) -> dict:
    if not withdrawal > 0:
        raise ValueError("withdrawal must be a positive dollar amount")
    warnings: list[str] = []
    total = sum(p["value"] for p in positions)

    if targets:
        sum_t = sum(targets.values())
        if any(v < 0 for v in targets.values()):
            raise ValueError("target percentages cannot be negative")
        if not sum_t > 0:
            raise ValueError("target percentages must sum to more than 0")
        if abs(sum_t - 100) > 0.01:
            warnings.append(f"Target percentages summed to {_m(round6(sum_t))}, not 100; normalized.")
        held = {p["symbol"] for p in positions}
        for s in targets:
            if s not in held:
                warnings.append(f"{s} has a target but is not held; ignored.")
        weights = {p["symbol"]: targets[p["symbol"]] / sum_t for p in positions if p["symbol"] in targets}
        hs = sum(weights.values())
        weights = {k: v / hs for k, v in weights.items()}
        left = [p["symbol"] for p in positions if p["symbol"] not in weights and p["value"] > 0]
        if left:
            warnings.append(f"Not in targets, left untouched: {', '.join(left)}.")
    else:
        weights = {p["symbol"]: p["value"] / total for p in positions}

    pool = [p for p in positions if p["symbol"] in weights]
    pool_value = sum(p["value"] for p in pool)
    if withdrawal > pool_value + 0.005:
        raise ValueError(f"Withdrawal ${_m(round2(withdrawal))} exceeds the ${_m(round2(pool_value))} available in the positions being traded.")

    # Water-filling: positions below target are frozen at their current value; re-solve the rest until stable.
    frozen: set[str] = set()
    desired: dict[str, float] = {}
    while True:
        active = [p for p in pool if p["symbol"] not in frozen]
        active_value = sum(p["value"] for p in active)
        active_weight = sum(weights[p["symbol"]] for p in active)
        end = active_value - withdrawal
        changed = False
        for p in active:
            d = (weights[p["symbol"]] / active_weight) * end if active_weight > 0 else p["value"]
            desired[p["symbol"]] = d
            if d > p["value"] + 1e-9:
                frozen.add(p["symbol"])
                changed = True
        if not changed:
            break
    for p in pool:
        if p["symbol"] in frozen:
            desired[p["symbol"]] = p["value"]
    if frozen:
        warnings.append(f"Already below target, not sold: {', '.join(sorted(frozen, key=[p['symbol'] for p in pool].index))}.")

    rows = []
    for p in positions:
        in_pool = p["symbol"] in weights
        want = desired[p["symbol"]] if in_pool else p["value"]
        sell_value = max(0.0, p["value"] - want)
        shares = sell_value / p["price"] if p["price"] > 0 else 0.0
        if p.get("is_cash"):
            shares = sell_value
        if whole_shares and not p.get("is_cash"):
            shares = math.floor(shares + 1e-9)
            sell_value = shares * p["price"]
        shares = min(shares, p["quantity"])
        proceeds = sell_value if p.get("is_cash") else shares * p["price"]
        rows.append({
            "symbol": p["symbol"],
            "shares_held": round6(p["quantity"]),
            "price": round2(p["price"]),
            "current_value": round2(p["value"]),
            "desired_pct": round6(weights[p["symbol"]] * 100) if in_pool else None,
            "desired_value": round2(want),
            "value_difference": round2(p["value"] - want),
            "shares_to_sell": round6(shares),
            "proceeds": round2(proceeds),
        })

    proceeds = round2(sum(r["proceeds"] for r in rows))
    ending = round2(total - withdrawal)
    for r in rows:
        r["post_value"] = round2(r["current_value"] - r["proceeds"])
        r["post_pct"] = round2(r["post_value"] / ending * 100) if ending > 0 else 0
    shortfall = round2(withdrawal - proceeds)
    if abs(shortfall) >= 0.01:
        side = "short of" if shortfall > 0 else "over"
        warnings.append(f"Sells raise ${_m(proceeds)}, {side} the ${_m(round2(withdrawal))} target by ${_m(abs(shortfall))} (rounding).")
    rows.sort(key=lambda r: (-r["proceeds"], -r["current_value"]))
    return {"starting_balance": round2(total), "withdrawal": round2(withdrawal), "ending_balance": ending,
            "total_proceeds": proceeds, "shortfall": shortfall, "rows": rows, "warnings": warnings}


# ------------------------------------------------------------------ with buys


def _resolve_weights(positions: list[dict], targets: dict | None, warnings: list[str]) -> dict[str, float]:
    user_gave = bool(targets)
    t: dict[str, float] = {}
    if user_gave:
        for k, v in targets.items():
            if v < 0:
                raise ValueError("target percentages cannot be negative")
            t[k.upper()] = v
    else:
        for p in positions:
            if not p.get("is_cash") and p["value"] > 0:
                t[p["symbol"]] = p["value"]  # keep the current mix
    if any(p.get("is_cash") for p in positions) and "CASH" not in t:
        t["CASH"] = 0
    held = {p["symbol"] for p in positions}
    for s in list(t):
        if s not in held:
            warnings.append(f"{s} has a target but is not held; ignored.")
            del t[s]
    total = sum(t.values())
    if not total > 0:
        raise ValueError("target percentages must sum to more than 0")
    if user_gave and abs(total - 100) > 0.01:
        warnings.append(f"Target percentages summed to {_m(round6(total))}, not 100; normalized.")
    left = [p["symbol"] for p in positions if p["symbol"] not in t and p["value"] > 0]
    if left:
        warnings.append(f"Not in targets, left untouched: {', '.join(left)}.")
    return {k: v / total for k, v in t.items()}


def _make_row(p: dict, weights: dict, desired: dict, trade: dict, ending: float) -> dict:
    in_pool = p["symbol"] in weights
    want = desired[p["symbol"]] if in_pool else p["value"]
    sell_amt, buy_amt = trade.get("sell_amt", 0.0), trade.get("buy_amt", 0.0)
    post = p["value"] - sell_amt + buy_amt
    return {
        "symbol": p["symbol"],
        "shares_held": round6(p["quantity"]),
        "price": round2(p["price"]),
        "current_value": round2(p["value"]),
        "desired_pct": round6(weights[p["symbol"]] * 100) if in_pool else None,
        "desired_value": round2(want),
        "value_difference": round2(p["value"] - want),
        "shares_to_sell": round6(trade.get("sell_shares", 0.0)),
        "proceeds": round2(sell_amt),
        "shares_to_buy": round6(trade.get("buy_shares", 0.0)),
        "buy_amount": round2(buy_amt),
        "post_value": round2(post),
        "post_pct": round2(post / ending * 100) if ending > 0 else 0,
    }


def _summarize(positions, withdrawal, rows, warnings, mode) -> dict:
    total = sum(p["value"] for p in positions)
    proceeds = round2(sum(r["proceeds"] for r in rows))
    buys = round2(sum(r["buy_amount"] for r in rows))
    cash_row = next((r for r in rows if r["symbol"] == "CASH"), None)
    shortfall = round2(withdrawal - (proceeds - buys))
    if abs(shortfall) >= 0.01:
        warnings.append(f"Net cash out is ${_m(round2(proceeds - buys))} vs the ${_m(round2(withdrawal))} target (off by ${_m(abs(shortfall))}).")
    rows.sort(key=lambda r: (-(r["proceeds"] + r["buy_amount"]), -r["current_value"]))
    return {"mode": mode, "starting_balance": round2(total), "withdrawal": round2(withdrawal),
            "ending_balance": round2(total - withdrawal), "total_proceeds": proceeds, "total_buys": buys,
            "cash_after": cash_row["post_value"] if cash_row else 0, "shortfall": shortfall,
            "rows": rows, "warnings": warnings}


def _with_buy_fields(plan: dict, mode: str) -> dict:
    cash = next((r for r in plan["rows"] if r["symbol"] == "CASH"), None)
    return {**plan, "mode": mode, "total_buys": 0, "cash_after": cash["post_value"] if cash else 0,
            "rows": [{**r, "shares_to_buy": 0, "buy_amount": 0} for r in plan["rows"]]}


def plan_rebalance(positions: list[dict], withdrawal: float, targets: dict | None = None,
                   whole_shares: bool = False, mode: str = "auto") -> dict:
    if not withdrawal >= 0:
        raise ValueError("withdrawal must be zero or a positive dollar amount")
    cash_pos = next((p for p in positions if p.get("is_cash")), None)
    cash = cash_pos["value"] if cash_pos else 0.0

    if mode == "auto":
        mode = "buy_only" if cash_pos and cash + 0.005 >= withdrawal else "cash_then_sell"
    if mode == "sell_only":
        return _with_buy_fields(plan_withdrawal(positions, withdrawal, targets, whole_shares), "sell_only")
    if mode == "cash_then_sell":
        return _cash_then_sell(positions, withdrawal, targets, whole_shares)

    warnings: list[str] = []
    weights = _resolve_weights(positions, targets, warnings)
    pool = [p for p in positions if p["symbol"] in weights]
    pool_value = sum(p["value"] for p in pool)
    if withdrawal > pool_value + 0.005:
        raise ValueError(f"Withdrawal ${_m(round2(withdrawal))} exceeds the ${_m(round2(pool_value))} available in the positions being traded.")
    ending = pool_value - withdrawal
    desired = {p["symbol"]: weights[p["symbol"]] * ending for p in pool}
    trades: dict[str, dict] = {}
    stocks = [p for p in pool if not p.get("is_cash")]

    def to_shares(v: float, p: dict) -> float:
        return math.floor(v / p["price"] + EPS) if whole_shares else v / p["price"]

    if mode == "buy_only":
        if not cash_pos or cash + 0.005 < withdrawal:
            raise ValueError(f'Cash ${_m(round2(cash))} does not cover the ${_m(round2(withdrawal))} withdrawal; use mode "auto", "sell_only" or "full".')
        cash_target = desired.get("CASH", 0.0)
        budget = max(0.0, cash - withdrawal - cash_target)
        if cash - withdrawal < cash_target - 0.005:
            warnings.append(f"Cash after the withdrawal (${_m(round2(cash - withdrawal))}) is below its ${_m(round2(cash_target))} target.")
        gaps = [(p, max(0.0, desired[p["symbol"]] - p["value"])) for p in stocks]
        gap_sum = sum(g for _, g in gaps)
        for p, gap in gaps:
            if not gap or not budget:
                continue
            spend = min(gap, budget * gap / gap_sum) if gap_sum > 0 else 0.0
            shares = to_shares(spend, p)
            if shares > 0:
                trades[p["symbol"]] = {"buy_shares": shares, "buy_amt": shares * p["price"]}
        spent = sum(t.get("buy_amt", 0.0) for t in trades.values())
        if budget - spent >= 0.01:
            why = " (whole-share rounding or all positions at target)" if whole_shares else " (all positions at target)"
            warnings.append(f"${_m(round2(budget - spent))} of leftover cash was not deployed{why}.")
        if gap_sum == 0 and budget > 0:
            warnings.append("No position is under target; nothing to buy.")
        used = withdrawal + spent
        trades["CASH"] = {"sell_shares": used, "sell_amt": used}
    elif mode == "full":
        for p in stocks:
            diff = p["value"] - desired[p["symbol"]]
            if diff > 0:
                shares = min(p["quantity"], to_shares(diff, p))
                trades[p["symbol"]] = {"sell_shares": shares, "sell_amt": shares * p["price"]}
            elif diff < 0:
                shares = to_shares(-diff, p)
                trades[p["symbol"]] = {"buy_shares": shares, "buy_amt": shares * p["price"]}

        def net() -> float:
            return sum(t.get("sell_amt", 0.0) - t.get("buy_amt", 0.0) for s, t in trades.items() if s != "CASH")

        # Whole-share rounding can leave cash short; drop buys one share at a time until it isn't.
        while cash + net() - withdrawal < -0.005:
            buys = sorted(((s, t) for s, t in trades.items() if t.get("buy_shares", 0) > 0), key=lambda st: -st[1]["buy_amt"])
            if not buys:
                raise ValueError('Cash cannot cover the withdrawal with these targets; try mode "sell_only".')
            sym, t = buys[0]
            price = t["buy_amt"] / t["buy_shares"]
            t["buy_shares"] -= 1
            t["buy_amt"] = t["buy_shares"] * price
            warnings.append(f"Dropped one share of {sym} so cash does not go negative.")
        if cash_pos:
            d = cash - (cash + net() - withdrawal)
            trades["CASH"] = {"sell_shares": d, "sell_amt": d} if d >= 0 else {"buy_shares": -d, "buy_amt": -d}
    else:
        raise ValueError(f'Unknown mode "{mode}" (use auto, sell_only, buy_only or full).')

    rows = [_make_row(p, weights, desired, trades.get(p["symbol"], {}), ending) for p in positions]
    return _summarize(positions, withdrawal, rows, warnings, mode)


def _cash_then_sell(positions: list[dict], withdrawal: float, targets: dict | None, whole_shares: bool) -> dict:
    """Use all cash first, then sell the remainder (sell-only math on the non-cash positions)."""
    cash_pos = next((p for p in positions if p.get("is_cash")), None)
    cash = cash_pos["value"] if cash_pos else 0.0
    rest = withdrawal - cash
    stocks = [p for p in positions if not p.get("is_cash")]
    t = {k: v for k, v in (targets or {}).items() if k.upper() != "CASH"}
    inner = plan_withdrawal(stocks, rest, t or None, whole_shares)
    total = sum(p["value"] for p in positions)
    ending = total - withdrawal
    rows = [{**r, "shares_to_buy": 0, "buy_amount": 0, "post_pct": round2(r["post_value"] / ending * 100) if ending > 0 else 0}
            for r in inner["rows"]]
    if cash_pos:
        rows.append({"symbol": "CASH", "shares_held": round6(cash), "price": 1, "current_value": round2(cash), "desired_pct": 0,
                     "desired_value": 0, "value_difference": round2(cash), "shares_to_sell": round6(cash), "proceeds": round2(cash),
                     "shares_to_buy": 0, "buy_amount": 0, "post_value": 0, "post_pct": 0})
    warnings = [f"Cash (${_m(round2(cash))}) is less than the withdrawal; used all of it and sold the remaining ${_m(round2(rest))}.", *inner["warnings"]]
    return _summarize(positions, withdrawal, rows, warnings, "cash_then_sell")
