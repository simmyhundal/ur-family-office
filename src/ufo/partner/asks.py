"""Spot messages where your partner asks whether the Joint account can cover things, so the trial's key number
("how often does my partner have to ask?") is measured automatically instead of by hand.

Pure text logic. Heuristic on purpose: it looks for money-state language (overdraft, enough cash, moving money into Joint,
covering rent or the card) and skips reactions ("Liked ..."). Use `scripts/partner_asks.py --review` to spot-check it.
Message text is never stored; only per-day counts are.
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import date

_TAPBACK = re.compile(r"^\s*(Liked|Loved|Disliked|Laughed at|Emphasized|Questioned|A ajouté un|A aimé|A adoré|A ri de)\b", re.I)
_PATTERNS = [
    r"overdraft|overdrawn|overdrawing",
    r"\b(enough|sufficient)\s+(money|cash|funds)\b",
    r"\b(do|did|will|would)\s+we\s+have\s+(the\s+)?(money|cash|enough)\b",
    r"\b(can|could|will)\s+(the\s+)?(joint|account)\s+(cover|handle|take)\b",
    r"\bcover(s|ed|ing)?\s+(the\s+|our\s+)?(rent|bills?|card|credit card|payment)\b",
    r"\b(is|are)\s+(the\s+)?(rent|bills?|card|credit card|payment)s?\s+(covered|paid|going through)\b",
    r"\bjoint\b.{0,40}\b(low|empty|short|balance|enough|cover|funds)\b",
    r"\b(low|short|empty)\b.{0,30}\bjoint\b",
    r"\bare\s+we\s+(good|ok|okay|covered)\b.{0,30}\b(money|rent|bills?|card|account|joint)\b",
]
_RE = re.compile("|".join(f"(?:{p})" for p in _PATTERNS), re.I)


# Looser "money-ish" words, used only to surface messages the matcher did NOT flag so it can be tuned by eye.
_MONEYISH = re.compile(r"joint|account|money|transfer|deposit|\brent\b|bills?\b|card|chase|bank|\$|overdraft|balance|cover|zelle|venmo|funds|payment|reminder", re.I)


def is_near_miss(text: str) -> bool:
    return bool(text) and not _TAPBACK.match(text) and not is_cash_ask(text) and bool(_MONEYISH.search(text))


# "put/add/move money into joint" is an ask only when phrased as a request. "I transferred it to the joint account" is an answer.
_MOVE_INTO_JOINT = re.compile(r"\b(put|add|move|send|transfer|deposit)\w*\b.{0,40}\b(in|into|to)\s+(the\s+|our\s+)?joint\b", re.I | re.S)
_REQUEST_CUE = re.compile(r"\b(reminder|remind|remember|forget|need to|needs to|have to|should|can you|could you|would you|will you|please|pls|mind|did you|have you|any chance|when are you|when will you)\b|\?", re.I)


def is_cash_ask(text: str) -> bool:
    if not text or _TAPBACK.match(text):
        return False
    if _RE.search(text):
        return True
    return bool(_MOVE_INTO_JOINT.search(text) and _REQUEST_CUE.search(text))


# "I paid / transferred / added money to the joint account" (also tolerates the common typo "join account").
_NOTICE = re.compile(
    r"\b(transfer\w*|transf\w*|paid|pay(ing)?|sent|send(ing)?|deposit\w*|added|adding|put|moved|moving|funded|topped)\b"
    r".{0,70}\b(joint(?!\s+(credit\s+)?cards?\b)|join\s+(account|chase|checking|acct))",
    re.I | re.S)


def is_payment_notice(text: str) -> bool:
    """Your own message saying you moved money into the joint account. Treated as the answer to an ask."""
    if not text or _TAPBACK.match(text):
        return False
    return bool(_NOTICE.search(text))


def count_notices_by_day(messages) -> dict[date, int]:
    """One per day at most: several messages about the same payment are a single answered ask."""
    return {d: 1 for d in sorted({m.when.date() for m in messages if m.from_me and is_payment_notice(m.text)})}


def merge_counts(auto: dict[date, int], manual: dict[date, int]) -> dict[date, int]:
    """Asks found in Messages plus asks you logged by hand (in person, calls, other apps)."""
    out = dict(auto)
    for d, n in manual.items():
        out[d] = out.get(d, 0) + n
    return dict(sorted(out.items()))


def count_by_day(messages) -> dict[date, int]:
    """The partner's asks per day. Accepts (when, text) pairs or ChatMessage tuples; your own messages are ignored here."""
    c: Counter = Counter()
    for m in messages:
        when, text = m[0], m[1]
        if len(m) > 2 and m[2]:  # from_me
            continue
        if is_cash_ask(text):
            c[when.date()] += 1
    return dict(sorted(c.items()))
