"""Gather the bills the alert should count: hand-entered, rent (recurring detection) and credit cards (Plaid Liabilities).

Never silently under-warns: every failure is returned as a note so the caller can say so in its output.
"""
from __future__ import annotations

from datetime import date

from ..config import Settings
from ..providers.plaid_client import get_credit_card_liabilities, get_recurring_outflows
from .bills import AlertConfig, BillSpec
from .detect import credit_card_bills, merge_bills, streams_to_bills


def collect_bills(settings: Settings, items: list[dict], cfg: AlertConfig, today: date) -> tuple[list[BillSpec], list[str], list[str]]:
    """Returns (bills, info_lines, failures). Manual bills always win over detected duplicates."""
    detected: list[BillSpec] = []
    info: list[str] = []
    failures: list[str] = []
    if cfg.rent_paid_from_joint or cfg.include_other_recurring:
        try:
            streams = get_recurring_outflows(settings, items, cfg.joint_mask)
            found, skipped = streams_to_bills(streams, today, cfg.include_early_detection, cfg.ignore_streams,
                                              cfg.rent_streams if cfg.rent_paid_from_joint else [], cfg.include_other_recurring)
            if not cfg.rent_paid_from_joint:  # rent is paid elsewhere: keep only the other recurring spend the user opted into
                found = [b for b in found if not any(r.casefold() in b.name.casefold() for r in cfg.rent_streams)]
            detected += found
            info += [f"skipped: {s}" for s in skipped]
            if cfg.rent_paid_from_joint and not any(b for b in found):
                info.append("no rent stream detected; add your landlord's name to rent_streams or enter rent as a manual bill")
        except RuntimeError as e:
            failures.append(f"recurring detection: {e}")
    if not cfg.rent_paid_from_joint:
        info.append("rent is not paid from Joint, so it counts as $0")
    if cfg.credit_card_masks:
        try:
            cards, skipped = credit_card_bills(get_credit_card_liabilities(settings, items, cfg.credit_card_masks), today, cfg.credit_card_amount)
            detected += cards
            info += [f"skipped: {s}" for s in skipped]
        except RuntimeError as e:
            failures.append(f"credit cards: {e}")
    else:
        info.append("credit_card_masks is empty, so no credit-card payments are counted")
    bills, dropped = merge_bills(cfg.bills, detected)
    return bills, info + [f"dropped: {d}" for d in dropped], failures
