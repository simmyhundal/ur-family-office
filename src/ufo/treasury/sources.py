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
    try:
        streams = get_recurring_outflows(settings, items, cfg.joint_mask)
        rent, skipped = streams_to_bills(streams, today, cfg.include_early_detection, cfg.ignore_streams, cfg.rent_streams, cfg.include_other_recurring)
        detected += rent
        info += [f"skipped: {s}" for s in skipped]
        if not rent:
            info.append("no rent stream detected; add your landlord's name to rent_streams or enter rent as a manual bill")
    except RuntimeError as e:
        failures.append(f"rent detection: {e}")
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
