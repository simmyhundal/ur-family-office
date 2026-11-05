import json
import re
from datetime import date, timedelta

import pytest

from jobs import check_balance as job
from ufo.config import Settings
from ufo.treasury import notify
from ufo.treasury.bills import AlertConfig, BillSpec
from ufo.treasury.low_balance import about_floor, check_balance
from ufo.treasury.notify import ConsoleNotifier, MultiNotifier, TelegramNotifier

TODAY = date(2026, 11, 3)


def cfg(**kw):
    base = dict(cushion=1500, next_topup=date(2026, 11, 30), joint_mask="4821", personal_mask="7390", personal_floor=1500,
                bills=[BillSpec(name="Chase Sapphire …9999 payment", amount=3210.80, due=date(2026, 11, 28))])
    base.update(kw)
    return AlertConfig(**base)


# ---- the "headroom" level: a checkable claim without exact figures
@pytest.mark.parametrize("n,expected", [(4909.55, "$4,500.00"), (500, "$500.00"), (499.99, "under $500.00"), (0, "under $500.00"), (-1, "below $0")])
def test_about_floor_rounds_down_to_the_nearest_500(n, expected):
    assert about_floor(n) == expected


def test_headroom_message_for_a_covered_joint_is_checkable_but_not_exact():
    r = check_balance(8120.35, 9000, cfg(), TODAY)  # lowest point 4909.55
    assert r.status == "ok"
    assert r.headroom_message == "UFO: Joint is covered through Nov 30, including upcoming bills. At its lowest it stays above $4,500.00 (your cushion is $1,500.00)."
    assert "4,909" not in r.headroom_message and "8,120" not in r.headroom_message and "3,210" not in r.headroom_message


def test_headroom_message_when_low_has_no_transfer_amount():
    r = check_balance(4000, 9000, cfg(), TODAY)  # 4000 - 3210.80 = 504.53 < 1500
    assert r.status == "low"
    assert r.headroom_message == "UFO: Joint may dip below its $1,500.00 cushion before Nov 28. Its lowest point is about $500.00."
    assert "Move" not in r.headroom_message and "transfer" not in r.headroom_message.lower()


@pytest.mark.parametrize("joint,personal", [(8120.35, 9000), (4000, 9000), (4000, 1500), (123.45, 98765.43), (-50, 1500), (60000, 4200)])
def test_headroom_message_never_leaks_exact_figures_accounts_or_bill_names(joint, personal):
    r = check_balance(joint, personal, cfg(), TODAY)
    m = r.headroom_message
    amounts = [float(x.replace(",", "")) for x in re.findall(r"\$([\d,]+(?:\.\d+)?)", m)]
    assert all(a == 1500.0 or a % 500 == 0 for a in amounts), f"only the cushion and $500-rounded figures: {amounts}"
    for secret in ("4821", "7390", "Sapphire", "9999", "3,210", "Chase", "Personal", f"{joint:,.2f}"):
        assert secret not in m


def test_minimal_message_is_unchanged_and_still_has_no_dollar_figures():
    r = check_balance(8120.35, 9000, cfg(), TODAY)
    assert r.public_message == "UFO: Joint is covered through Nov 30." and "$" not in r.public_message


# ---- per-chat levels in the Telegram notifier
TG = Settings(telegram_bot_token="123:SECRET", telegram_chat_ids=["111", "-222"])
MSGS = {"minimal": "MIN", "headroom": "HEAD"}


@pytest.fixture
def sent(monkeypatch):
    calls = []

    class Resp:
        def read(self):
            return b'{"ok": true}'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(notify.urllib.request, "urlopen", lambda req, timeout: calls.append(json.loads(req.data)) or Resp())
    return calls


def test_each_chat_gets_its_own_level_and_defaults_to_minimal(sent):
    TelegramNotifier(TG, {"-222": "headroom"}).send_tiered(MSGS)
    assert [(c["chat_id"], c["text"]) for c in sent] == [("111", "MIN"), ("-222", "HEAD")]


def test_unknown_levels_fall_back_to_minimal_never_to_something_richer(sent):
    TelegramNotifier(TG, {"111": "full", "-222": "everything"}).send_tiered(MSGS)  # "full" is not a Telegram level
    assert [c["text"] for c in sent] == ["MIN", "MIN"]


def test_plain_send_is_minimal_for_every_chat(sent):
    TelegramNotifier(TG, {"-222": "headroom"}).send("only text")
    assert [c["text"] for c in sent] == ["only text", "only text"]


def test_console_dry_run_shows_the_levels_that_would_be_used(capsys):
    ConsoleNotifier().send_tiered(MSGS, {"-222": "headroom"})
    out = capsys.readouterr().out
    assert "[dry run, not sent, minimal] MIN" in out and "[dry run, not sent, headroom] HEAD" in out
    ConsoleNotifier().send_tiered(MSGS, {})
    assert "HEAD" not in capsys.readouterr().out


def test_multi_notifier_forwards_levels_and_sms_gets_minimal_only():
    got = {}

    class Tg:
        def send_tiered(self, messages, levels=None):
            got["tg"] = (messages, levels)

    class Sms:
        def send(self, m):
            got["sms"] = m

    MultiNotifier([Tg(), Sms()]).send_tiered(MSGS, {"x": "headroom"})
    assert got["tg"] == (MSGS, {"x": "headroom"}) and got["sms"] == "MIN"


# ---- the job: heartbeat and per-chat levels
class FakeNotifier:
    def __init__(self):
        self.tiers, self.levels = None, None

    def send_tiered(self, messages, levels=None):
        self.tiers, self.levels = messages, levels


def write_cfg(tmp_path, **extra):
    (tmp_path / ".data").mkdir(exist_ok=True)
    p = tmp_path / ".data" / "alert.json"
    p.write_text(json.dumps({"cushion": 1000, "next_topup": str(date.today() + timedelta(days=10)), "joint_mask": "4821",
                             "personal_mask": "7390", "personal_floor": 1500, "bills": [], **extra}))
    return str(p)


@pytest.fixture
def fake_notifier(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    n = FakeNotifier()
    monkeypatch.setattr(job, "build_notifier", lambda settings, channel, levels=None: n)
    return n


def test_a_covered_heartbeat_is_sent_only_when_asked_for(tmp_path, fake_notifier):
    job.main(["--config", write_cfg(tmp_path), "--joint", "5000", "--personal", "4200", "--send"])
    assert fake_notifier.tiers is None  # default: silence when all is well
    job.main(["--config", write_cfg(tmp_path, notify_when_ok=True), "--joint", "5000", "--personal", "4200", "--send"])
    assert fake_notifier.tiers["minimal"].startswith("UFO: Joint is covered through")
    assert fake_notifier.tiers["headroom"].startswith("UFO: Joint is covered through") and "your cushion is $1,000.00" in fake_notifier.tiers["headroom"]


def test_messages_carry_a_checked_time_so_a_recipient_can_tell_it_is_fresh(tmp_path, fake_notifier):
    job.main(["--config", write_cfg(tmp_path, notify_when_ok=True), "--joint", "5000", "--personal", "4200", "--send"])
    assert re.search(r"Checked \w{3} \w{3} \d{1,2}, \d{1,2}:\d{2} [AP]M\.$", fake_notifier.tiers["minimal"])


def test_chat_levels_from_the_config_reach_the_notifier(tmp_path, fake_notifier):
    job.main(["--config", write_cfg(tmp_path, notify_when_ok=True, telegram_detail={"-222": "headroom"}), "--joint", "5000", "--personal", "4200", "--send"])
    assert fake_notifier.levels == {"-222": "headroom"}


def test_a_chat_level_of_full_is_rejected_by_the_config(tmp_path):
    with pytest.raises(Exception):
        AlertConfig.model_validate({"joint_mask": "1", "personal_mask": "2", "telegram_detail": {"-222": "full"}})
