import sqlite3
from datetime import datetime

import pytest

from ufo.partner.asks import count_by_day, is_cash_ask
from ufo.partner.imessage import APPLE_EPOCH, PartnerConfig, decode_body, read_partner_messages

# Invented examples of the shapes the matcher targets. No real messages are used anywhere in this repo.
ASKS = [
    "Worried we'll overdraft before payday",
    "Is there enough money in there for the card?",
    "Could you move some money into the joint account?",
    "I think we might overdraft if rent goes out first",
    "Is rent covered this month?",
    "Can the joint cover the credit card payment?",
    "Joint looks low again",
    "Are we good on bills this week?",
]
NOT_ASKS = [
    "Do we have any milk left?",
    "Loved “see you at seven”",
    "Liked “running a bit late”",
    "Can you grab the dry cleaning on your way home?",
    "Paid the electrician in cash yesterday",
    "Dinner at 7?",
    "Joint pain is back, ugh",
    "",
]


@pytest.mark.parametrize("text", ASKS)
def test_detects_cash_asks(text):
    assert is_cash_ask(text), text


@pytest.mark.parametrize("text", NOT_ASKS)
def test_ignores_everything_else(text):
    assert not is_cash_ask(text), text


def test_counts_per_day():
    msgs = [(datetime(2026, 3, 10, 9), ASKS[0]), (datetime(2026, 3, 10, 20), ASKS[2]), (datetime(2026, 6, 16, 8), "hi"), (datetime(2026, 4, 20, 8), ASKS[4])]
    out = count_by_day(msgs)
    assert {d.isoformat(): n for d, n in out.items()} == {"2026-03-10": 2, "2026-04-20": 1}


def test_decode_attributed_body():
    blob = b"\x04\x0bstreamtyped\x81\xe8\x03\x84\x01@\x84\x84\x84\x12NSAttributedString\x00\x84\x84\x08NSObject\x00\x85\x92\x84\x84\x84\x08NSString\x01\x94\x84\x01+\x0fhello from blob\x86"
    assert decode_body(None, blob) == "hello from blob"
    assert decode_body("plain", None) == "plain" and decode_body(None, None) == ""


def make_db(path):
    c = sqlite3.connect(path)
    c.executescript("""
      create table handle(ROWID integer primary key, id text);
      create table message(ROWID integer primary key, date integer, text text, attributedBody blob, is_from_me integer, handle_id integer);
      create table chat_message_join(chat_id integer, message_id integer);
    """)
    c.executemany("insert into handle values(?,?)", [(1, "+15550001111"), (2, "+15550002222")])
    ns = lambda d: int((d - APPLE_EPOCH).total_seconds() * 1e9)  # noqa: E731
    rows = [
        (1, ns(datetime(2026, 3, 10, 9)), "Worried we'll overdraft before payday", None, 0, 1),       # partner, watched chat
        (2, ns(datetime(2026, 3, 10, 10)), "Worried we'll overdraft before payday too", None, 0, 2),   # someone else
        (3, ns(datetime(2026, 3, 10, 11)), "Worried we'll overdraft before payday", None, 1, 0),       # from me
        (4, ns(datetime(2026, 3, 10, 12)), "Worried we'll overdraft before payday", None, 0, 1),       # partner, other chat
        (5, ns(datetime(2025, 1, 1, 12)), "old message", None, 0, 1),                            # before the window
    ]
    c.executemany("insert into message values(?,?,?,?,?,?)", rows)
    c.executemany("insert into chat_message_join values(?,?)", [(10, 1), (10, 2), (10, 3), (99, 4), (10, 5)])
    c.commit()
    c.close()


def test_reader_only_returns_the_partners_messages_in_the_watched_chats(tmp_path):
    db = str(tmp_path / "chat.db")
    make_db(db)
    cfg = PartnerConfig(chat_ids=[10], sender_number_suffixes=["1111"], db_path=db)
    got = read_partner_messages(cfg, since=datetime(2026, 1, 1), until=datetime(2026, 12, 31))
    assert [t for _, t in got] == ["Worried we'll overdraft before payday"] and got[0][0] == datetime(2026, 3, 10, 9)
    assert read_partner_messages(PartnerConfig(chat_ids=[10], sender_number_suffixes=["9999"], db_path=db), datetime(2026, 1, 1)) == []


def test_reader_opens_the_database_read_only(tmp_path):
    db = str(tmp_path / "chat.db")
    make_db(db)
    before = (tmp_path / "chat.db").read_bytes()
    read_partner_messages(PartnerConfig(chat_ids=[10], sender_number_suffixes=["1111"], db_path=db), datetime(2026, 1, 1))
    assert (tmp_path / "chat.db").read_bytes() == before


def test_merge_counts_adds_manual_asks_to_automatic_ones():
    from datetime import date

    from ufo.partner.asks import merge_counts

    out = merge_counts({date(2026, 3, 10): 2}, {date(2026, 3, 10): 1, date(2026, 5, 1): 1})
    assert {d.isoformat(): n for d, n in out.items()} == {"2026-03-10": 3, "2026-05-01": 1}


def test_one_person_under_several_handles_is_found_by_number_or_email(tmp_path):
    import sqlite3

    db = str(tmp_path / "chat.db")
    make_db(db)
    c = sqlite3.connect(db)
    c.execute("insert into handle values(3, 'Partner@Example.com')")
    c.execute("insert into message values(6, ?, 'Is rent covered this month?', null, 0, 3)", (int((datetime(2026, 3, 11) - APPLE_EPOCH).total_seconds() * 1e9),))
    c.execute("insert into chat_message_join values(10, 6)")
    c.commit(); c.close()
    only_number = PartnerConfig(chat_ids=[10], sender_number_suffixes=["1111"], db_path=db)
    both = PartnerConfig(chat_ids=[10], sender_number_suffixes=["1111"], sender_emails=["partner@example.com"], db_path=db)
    assert len(read_partner_messages(only_number, datetime(2026, 1, 1), datetime(2026, 12, 31))) == 1  # the email handle was invisible
    assert len(read_partner_messages(both, datetime(2026, 1, 1), datetime(2026, 12, 31))) == 2


def test_discover_lists_senders_masked(tmp_path):
    import sqlite3

    from ufo.partner.imessage import describe_senders

    db = str(tmp_path / "chat.db")
    make_db(db)
    c = sqlite3.connect(db)
    c.execute("insert into handle values(3, 'partner@example.com')")
    c.execute("insert into message values(6, ?, 'hi', null, 0, 3)", (int((datetime(2026, 3, 11) - APPLE_EPOCH).total_seconds() * 1e9),))
    c.execute("insert into chat_message_join values(10, 6)")
    c.commit(); c.close()
    out = dict(describe_senders(PartnerConfig(chat_ids=[10], sender_number_suffixes=[], db_path=db), datetime(2026, 1, 1)))
    assert "p…@example.com" in out and "…1111" in out and "…2222" in out  # masked: never the full number or email
    assert not any("partner@" in k or "5550001111" in k for k in out)
