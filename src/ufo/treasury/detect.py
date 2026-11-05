"""Turn Plaid recurring-transaction streams into bills, and merge them with hand-entered ones.

Pure logic (no I/O). Stream dicts follow Plaid's /transactions/recurring/get outflow_streams shape.
Conservative by design: the larger of the last and average amount is used, and anything uncertain is reported, not hidden.
"""
from __future__ import annotations

from datetime import date, timedelta

from .bills import BillSpec, Repeat

FREQ: dict[str, Repeat] = {"WEEKLY": "weekly", "BIWEEKLY": "biweekly", "SEMI_MONTHLY": "semi_monthly",
                           "MONTHLY": "monthly", "ANNUALLY": "annually", "UNKNOWN": "none"}
LATE_GRACE_DAYS = 5  # a predicted date this recently passed may just not have posted yet: count it as due today


def _val(x):
    return getattr(x, "value", x)


def _amount(a) -> float:
    return abs(float((a or {}).get("amount") or 0))


def stream_to_bill(stream: dict, today: date, include_early: bool = False, ignore: list[str] | None = None) -> tuple[BillSpec | None, str | None]:
    """Returns (bill, None) or (None, reason it was skipped)."""
    name = (stream.get("merchant_name") or stream.get("description") or "Unknown").strip()
    if any(i.casefold() in name.casefold() for i in (ignore or [])):
        return None, f"{name}: in your ignore list"
    if not stream.get("is_active", True):
        return None, f"{name}: inactive"
    status = _val(stream.get("status")) or "UNKNOWN"
    if status == "TOMBSTONED":
        return None, f"{name}: stopped recurring"
    if status == "EARLY_DETECTION" and not include_early:
        return None, f"{name}: still early detection (set include_early_detection to count it)"
    pfc = stream.get("personal_finance_category") or {}
    detailed = _val(pfc.get("detailed")) or ""
    if detailed.startswith("TRANSFER_OUT") or _val(pfc.get("primary")) == "TRANSFER_OUT":
        return None, f"{name}: a transfer, not a bill"
    nxt = stream.get("predicted_next_date")
    if isinstance(nxt, str):
        nxt = date.fromisoformat(nxt)
    if nxt is None:
        return None, f"{name}: no predicted next date"
    if nxt < today:
        if today - nxt > timedelta(days=LATE_GRACE_DAYS):
            return None, f"{name}: predicted date {nxt} is long past"
        nxt = today
    amount = round(max(_amount(stream.get("last_amount")), _amount(stream.get("average_amount"))), 2)
    if amount <= 0:
        return None, f"{name}: no amount"
    return BillSpec(name=name, amount=amount, due=nxt, repeat=FREQ.get(_val(stream.get("frequency")) or "UNKNOWN", "none"), source="plaid"), None


def streams_to_bills(streams: list[dict], today: date, include_early: bool = False,
                     ignore: list[str] | None = None) -> tuple[list[BillSpec], list[str]]:
    bills, skipped = [], []
    for st in streams:
        b, why = stream_to_bill(st, today, include_early, ignore)
        if b:
            bills.append(b)
        else:
            skipped.append(why)
    return bills, skipped


def _same(manual: BillSpec, detected: BillSpec) -> bool:
    a, b = manual.name.casefold(), detected.name.casefold()
    if a == b or a in b or b in a:
        return True
    return abs(manual.amount - detected.amount) <= 1.0 and abs((manual.due - detected.due).days) <= 3


def merge_bills(manual: list[BillSpec], detected: list[BillSpec]) -> tuple[list[BillSpec], list[str]]:
    """Manual bills always win; a detected bill that matches one (by name, or by amount +/- $1 and date +/- 3 days) is dropped."""
    kept, dropped = [], []
    for d in detected:
        m = next((m for m in manual if _same(m, d)), None)
        if m:
            dropped.append(f"{d.name} (${d.amount:,.2f}): already covered by your manual bill '{m.name}'")
        else:
            kept.append(d)
    return [*manual, *kept], dropped
