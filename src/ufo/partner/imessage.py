"""Read-only access to your own Messages history (macOS chat.db) for one person's messages in specific chats.

Needs Full Disk Access for the app running it (Terminal / Claude). Opens the database read-only, returns only messages
sent BY the given person in the given chats, and never writes message text anywhere.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from pydantic import BaseModel

APPLE_EPOCH = datetime(2001, 1, 1)


class PartnerConfig(BaseModel):
    chat_ids: list[int]  # Messages chat ROWIDs: the 1:1 thread(s) and the group chat
    sender_number_suffixes: list[str]  # last digits of the partner's phone number(s)
    db_path: str = str(Path.home() / "Library/Messages/chat.db")


def decode_body(text: str | None, blob: bytes | None) -> str:
    """Newer macOS stores message text in attributedBody (a typedstream blob) instead of `text`."""
    if text:
        return text
    if not blob:
        return ""
    try:
        b = bytes(blob).split(b"NSString")[1][5:]
        if b[0] == 0x81:
            n, b = int.from_bytes(b[1:3], "little"), b[3:]
        else:
            n, b = b[0], b[1:]
        return b[:n].decode("utf8", "ignore")
    except Exception:
        return ""


def read_partner_messages(cfg: PartnerConfig, since: datetime, until: datetime | None = None) -> list[tuple[datetime, str]]:
    con = sqlite3.connect(f"file:{cfg.db_path}?mode=ro", uri=True)
    digits = lambda s: re.sub(r"\D", "", s or "")  # noqa: E731
    handles = [r for r, i in con.execute("select ROWID, id from handle") if digits(i)[-4:] in {x[-4:] for x in cfg.sender_number_suffixes}]
    if not handles or not cfg.chat_ids:
        return []
    ns = lambda d: int((d - APPLE_EPOCH).total_seconds() * 1e9)  # noqa: E731
    q = f"""select msg.date, msg.text, msg.attributedBody from message msg
            join chat_message_join m on m.message_id = msg.ROWID
            where m.chat_id in ({",".join("?" * len(cfg.chat_ids))}) and msg.is_from_me = 0
              and msg.handle_id in ({",".join("?" * len(handles))}) and msg.date >= ? and msg.date < ?
            order by msg.date"""
    end = until or datetime.now() + timedelta(days=1)
    rows = con.execute(q, [*cfg.chat_ids, *handles, ns(since), ns(end)]).fetchall()
    return [(APPLE_EPOCH + timedelta(seconds=d / 1e9), decode_body(t, b)) for d, t, b in rows]
