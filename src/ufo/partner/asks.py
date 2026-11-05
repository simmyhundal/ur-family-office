"""Spot messages where your partner asks whether the Joint account can cover things, so the trial's key number
("how often does my partner have to ask?") is measured automatically instead of by hand.

Pure text logic. Heuristic on purpose: it looks for money-state language (overdraft, enough cash, moving money into Joint,
covering rent or the card) and skips reactions ("Liked ..."). Use `scripts/partner_asks.py --review` to spot-check it.
Message text is never stored; only per-day counts are.
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import date, datetime

_TAPBACK = re.compile(r"^\s*(Liked|Loved|Disliked|Laughed at|Emphasized|Questioned)\s+[“\"']", re.I)
_PATTERNS = [
    r"overdraft|overdrawn|overdrawing",
    r"\b(enough|sufficient)\s+(money|cash|funds)\b",
    r"\b(do|did|will|would)\s+we\s+have\s+(the\s+)?(money|cash|enough)\b",
    r"\b(can|could|will)\s+(the\s+)?(joint|account)\s+(cover|handle|take)\b",
    r"\bcover(s|ed|ing)?\s+(the\s+|our\s+)?(rent|bills?|card|credit card|payment)\b",
    r"\b(is|are)\s+(the\s+)?(rent|bills?|card|credit card|payment)s?\s+(covered|paid|going through)\b",
    r"\b(put|add|move|send|transfer)\w*\b.{0,40}\b(in|into|to)\s+(the\s+|our\s+)?joint\b",
    r"\bjoint\b.{0,40}\b(low|empty|short|balance|enough|cover|funds)\b",
    r"\b(low|short|empty)\b.{0,30}\bjoint\b",
    r"\bare\s+we\s+(good|ok|okay|covered)\b.{0,30}\b(money|rent|bills?|card|account|joint)\b",
]
_RE = re.compile("|".join(f"(?:{p})" for p in _PATTERNS), re.I)


# Looser "money-ish" words, used only to surface messages the matcher did NOT flag so it can be tuned by eye.
_MONEYISH = re.compile(r"joint|account|money|transfer|deposit|\brent\b|bills?\b|card|chase|bank|\$|overdraft|balance|cover|zelle|venmo|funds|payment|reminder", re.I)


def is_near_miss(text: str) -> bool:
    return bool(text) and not _TAPBACK.match(text) and not is_cash_ask(text) and bool(_MONEYISH.search(text))


def is_cash_ask(text: str) -> bool:
    if not text or _TAPBACK.match(text):
        return False
    return bool(_RE.search(text))


def merge_counts(auto: dict[date, int], manual: dict[date, int]) -> dict[date, int]:
    """Asks found in Messages plus asks you logged by hand (in person, calls, other apps)."""
    out = dict(auto)
    for d, n in manual.items():
        out[d] = out.get(d, 0) + n
    return dict(sorted(out.items()))


def count_by_day(messages: list[tuple[datetime, str]]) -> dict[date, int]:
    c: Counter = Counter()
    for when, text in messages:
        if is_cash_ask(text):
            c[when.date()] += 1
    return dict(sorted(c.items()))
