"""Per-account withdrawals in one call (e.g. X from *154, 10X from *693). Port of fin-advisor's plan.mjs."""
from __future__ import annotations

from .engine import aggregate_by_symbol, plan_rebalance, round2


def _matches(h: dict, mask: str | None) -> bool:
    if not mask:
        return True
    m = h.get("account_mask") or ""
    return m == mask or (len(mask) >= 3 and m.endswith(mask))


def _cash_of(holdings: list[dict], mask: str | None) -> float:
    return sum(h["value"] for h in holdings if h.get("is_cash") and _matches(h, mask))


def plan_from_holdings(holdings: list[dict], spec: dict) -> dict:
    """spec: {withdrawals: [{account_mask?, amount?: number|'all_cash', multiple?, target_weights?, mode?}],
              base_amount?, base_all_cash_of?, target_weights?, mode?, whole_shares?}"""
    withdrawals = spec.get("withdrawals")
    if not withdrawals:
        raise ValueError("Provide at least one withdrawal.")
    base = spec.get("base_amount")
    if base is None and spec.get("base_all_cash_of"):
        base = _cash_of(holdings, spec["base_all_cash_of"])
        if not base > 0:
            raise ValueError(f"Account {spec['base_all_cash_of']} has no cash to use as the base amount.")

    plans = []
    for w in withdrawals:
        amount = w.get("amount")
        mask = w.get("account_mask")
        if amount == "all_cash":
            amount = _cash_of(holdings, mask)
        elif amount is None and w.get("multiple") is not None:
            if base is None:
                raise ValueError('"multiple" needs base_amount or base_all_cash_of.')
            amount = round2(base * w["multiple"])
        if not isinstance(amount, (int, float)) or isinstance(amount, bool) or not amount >= 0:
            raise ValueError(f"Invalid withdrawal amount for account {mask or 'all'}.")
        scoped = [h for h in holdings if _matches(h, mask)]
        if not scoped:
            raise ValueError(f"No holdings found for account {mask or '(all)'}.")
        plan = plan_rebalance(aggregate_by_symbol(scoped), amount,
                              targets=w.get("target_weights") or spec.get("target_weights"),
                              mode=w.get("mode") or spec.get("mode") or "auto",
                              whole_shares=spec.get("whole_shares", False))
        plans.append({"account": f"…{mask}" if mask else "all accounts combined", **plan})

    return {"summary": {"total_withdrawal": round2(sum(p["withdrawal"] for p in plans)),
                        "total_proceeds": round2(sum(p["total_proceeds"] for p in plans)),
                        "total_buys": round2(sum(p["total_buys"] for p in plans))},
            "plans": plans}
