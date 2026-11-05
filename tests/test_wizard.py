import json
import os
import stat
from datetime import date
from pathlib import Path

import pytest

from ufo.config import Settings
from ufo.setup import wizard
from ufo.setup.envfile import update_env
from ufo.setup.wizard import Deps, next_monthly_date
from ufo.treasury.bills import AlertConfig

TOKEN = "123456:SECRET-TOKEN-VALUE"
ACCOUNTS = [
    {"name": "Chase Joint Checking", "mask": "4821", "type": "depository", "subtype": "checking"},
    {"name": "Chase Personal Checking", "mask": "7390", "type": "depository", "subtype": "checking"},
    {"name": "Chase Freedom", "mask": "9999", "type": "credit", "subtype": "credit card"},
    {"name": "Chase Sapphire", "mask": "5555", "type": "credit", "subtype": "credit card"},
]


class Script:
    """Answers prompts by key; records everything the wizard says."""

    def __init__(self, **answers):
        self.a, self.said, self.asked = answers, [], []

    def _get(self, key, default=None):
        self.asked.append(key)
        v = self.a.get(key, default)
        if isinstance(v, list) and key in self.a and self.a[key] and isinstance(self.a[key][0], dict):
            return v
        return v

    def say(self, text=""):
        self.said.append(text)

    def ask(self, key, text, default=None):
        v = self._get(key, default)
        return default if v is None else str(v)

    def secret(self, key, text):
        v = self.a[key]
        if isinstance(v, list):
            return v.pop(0)
        return v

    def confirm(self, key, text, default=True):
        v = self._get(key, default)
        return default if v is None else (v.pop(0) if isinstance(v, list) else v)

    def choose(self, key, text, options):
        return self.a[key]

    def choose_many(self, key, text, options):
        return self.a.get(key, [])

    @property
    def output(self):
        return "\n".join(self.said)


class FakeAdmin:
    def __init__(self, token, polls=None, bad=False):
        if bad:
            raise RuntimeError("bad token")
        self.token, self.polls, self.hardened = token, polls if polls is not None else [{111: "Pat Example"}], False

    def me(self):
        return {"username": "ufo_alert_bot"}

    def people_who_messaged(self):
        return self.polls.pop(0) if len(self.polls) > 1 else self.polls[0]

    def harden(self):
        self.hardened = True
        return ["Bot can be added to groups. In @BotFather: Bot Settings > Allow Groups? > Turn off."]


class FakeNotifier:
    sent: list = []

    def __init__(self, settings):
        self.settings = settings

    def send(self, m):
        FakeNotifier.sent.append((self.settings.telegram_chat_ids, m))


@pytest.fixture(autouse=True)
def _restore_environment():
    """The wizard writes os.environ (so later steps see new values); never let that leak into other tests."""
    snap = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(snap)


@pytest.fixture
def deps(tmp_path, monkeypatch):
    for k in ("PLAID_CLIENT_ID", "PLAID_SECRET", "PLAID_ENV", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_IDS"):
        monkeypatch.delenv(k, raising=False)
    FakeNotifier.sent = []
    (tmp_path / ".env").write_text("PLAID_CLIENT_ID=cid\nPLAID_SECRET=sec\nPLAID_ENV=production\n")
    monkeypatch.setenv("PLAID_CLIENT_ID", "cid")
    monkeypatch.setenv("PLAID_SECRET", "sec")
    monkeypatch.setenv("PLAID_ENV", "production")
    link_calls = []
    d = Deps(root=tmp_path, today=lambda: date(2026, 11, 20), sleep=lambda s: None,
             load_settings=lambda: Settings(plaid_client_id=os.environ.get("PLAID_CLIENT_ID"), plaid_secret=os.environ.get("PLAID_SECRET"),
                                           telegram_bot_token=os.environ.get("TELEGRAM_BOT_TOKEN"),
                                           telegram_chat_ids=[c for c in os.environ.get("TELEGRAM_CHAT_IDS", "").split(",") if c]),
             load_items=lambda: [{"item_id": "i", "access_token": "t"}], link_account=lambda s: link_calls.append(1),
             list_accounts=lambda s, items: ACCOUNTS, make_admin=lambda t: FakeAdmin(t), make_notifier=FakeNotifier)
    d.link_calls = link_calls
    return d


HAPPY = dict(joint=0, personal=0, cards=[0], rent=False, deposit=True, deposit_name="Rent match from Personal", deposit_amount="1,800",
             deposit_day="2", deposit_from_personal=True, floor="1500", cushion="1000", lookahead="14", telegram=True,
             tg_token=TOKEN, tg_test=True)


def test_happy_path_writes_config_env_and_sends_a_test(deps):
    p = Script(**HAPPY)
    wizard.run(p, deps)
    cfg = json.loads((deps.root / ".data" / "alert.json").read_text())
    AlertConfig.model_validate(cfg)  # the file is a valid config
    assert cfg["joint_mask"] == "4821" and cfg["personal_mask"] == "7390" and cfg["credit_card_masks"] == ["9999"]
    assert cfg["rent_paid_from_joint"] is False and cfg["personal_floor"] == 1500 and cfg["cushion"] == 1000 and cfg["detect_bills"] is True
    assert cfg["scheduled_deposits"] == [{"name": "Rent match from Personal", "amount": 1800.0, "due": "2026-12-02", "repeat": "monthly", "from_personal": True}]
    env = (deps.root / ".env").read_text()
    assert f"TELEGRAM_BOT_TOKEN={TOKEN}" in env and "TELEGRAM_CHAT_IDS=111" in env and "PLAID_CLIENT_ID=cid" in env  # existing keys kept
    assert FakeNotifier.sent and FakeNotifier.sent[0][0] == ["111"] and "UFO test" in FakeNotifier.sent[0][1]


def test_secrets_are_never_printed_and_files_are_owner_only(deps):
    p = Script(**HAPPY)
    wizard.run(p, deps)
    assert TOKEN not in p.output and "SECRET-TOKEN" not in p.output
    for f in (deps.root / ".env", deps.root / ".data" / "alert.json"):
        assert stat.S_IMODE(f.stat().st_mode) == 0o600


def test_the_wizard_says_what_it_cannot_automate_and_shows_hardening_warnings(deps):
    p = Script(**HAPPY)
    wizard.run(p, deps)
    assert "@BotFather" in p.output and "/newbot" in p.output
    assert "Allow Groups" in p.output


def test_rent_from_joint_asks_for_the_landlord_and_turns_detection_on(deps):
    p = Script(**{**HAPPY, "cards": [], "rent": True, "landlord": "Acme Property Mgmt", "deposit": False, "telegram": False})
    wizard.run(p, deps)
    cfg = json.loads((deps.root / ".data" / "alert.json").read_text())
    assert cfg["rent_paid_from_joint"] is True and cfg["rent_streams"] == ["Acme Property Mgmt"] and cfg["scheduled_deposits"] == [] and cfg["detect_bills"] is True


def test_no_rent_no_cards_means_no_detection(deps):
    p = Script(**{**HAPPY, "cards": [], "deposit": False, "telegram": False})
    wizard.run(p, deps)
    cfg = json.loads((deps.root / ".data" / "alert.json").read_text())
    assert cfg["detect_bills"] is False and cfg["rent_paid_from_joint"] is False  # rent defaults to $0


def test_existing_config_is_not_overwritten_without_consent_and_is_backed_up_with_it(deps):
    path = deps.root / ".data" / "alert.json"
    path.parent.mkdir()
    path.write_text('{"old": true}')
    wizard.run(Script(**{**HAPPY, "telegram": False, "overwrite": False}), deps)
    assert json.loads(path.read_text()) == {"old": True}
    wizard.run(Script(**{**HAPPY, "telegram": False, "overwrite": True}), deps)
    assert json.loads(path.with_suffix(".json.bak").read_text()) == {"old": True} and "joint_mask" in path.read_text()


def test_bad_token_is_retried_then_skipped_without_saving_anything(deps):
    deps.make_admin = lambda t: FakeAdmin(t, bad=True)
    p = Script(**{**HAPPY, "tg_token": [TOKEN, TOKEN, TOKEN]})
    wizard.run(p, deps)
    assert "did not work" in p.output and "TELEGRAM_BOT_TOKEN" not in (deps.root / ".env").read_text()
    assert (deps.root / ".data" / "alert.json").exists()  # the rest of the setup still completed


def test_waits_for_people_to_message_the_bot_then_picks_recipients(deps):
    deps.make_admin = lambda t: FakeAdmin(t, polls=[{}, {}, {111: "Pat Example", 222: "Sam Example"}])
    wizard.run(Script(**{**HAPPY, "tg_more": False, "tg_who": [1]}), deps)
    assert "TELEGRAM_CHAT_IDS=222" in (deps.root / ".env").read_text()  # only the second person was chosen


def test_nobody_messaged_the_bot_means_no_recipients_saved(deps):
    deps.poll_seconds = 6
    deps.make_admin = lambda t: FakeAdmin(t, polls=[{}])
    p = Script(**{**HAPPY, "tg_retry": False})
    wizard.run(p, deps)
    assert "TELEGRAM_CHAT_IDS" not in (deps.root / ".env").read_text() and "alerts are not enabled" in p.output
    assert FakeNotifier.sent == []


def test_links_plaid_when_nothing_is_linked_yet(deps):
    state = {"items": []}
    deps.load_items = lambda: state["items"]
    deps.link_account = lambda s: state["items"].append({"item_id": "i", "access_token": "t"}) or deps.link_calls.append(1)
    wizard.run(Script(**{**HAPPY, "telegram": False, "link": True}), deps)
    assert deps.link_calls == [1]


def test_asks_for_plaid_keys_when_missing_and_saves_them_hidden(deps, monkeypatch):
    (deps.root / ".env").write_text("")
    for k in ("PLAID_CLIENT_ID", "PLAID_SECRET"):
        monkeypatch.delenv(k)
    p = Script(**{**HAPPY, "telegram": False, "plaid_client_id": "new-id", "plaid_secret": "new-secret", "plaid_env": "sandbox"})
    wizard.run(p, deps)
    env = (deps.root / ".env").read_text()
    assert "PLAID_CLIENT_ID=new-id" in env and "PLAID_SECRET=new-secret" in env and "PLAID_ENV=sandbox" in env
    assert "new-secret" not in p.output


def test_no_linked_accounts_falls_back_to_typing_the_digits(deps):
    deps.load_items = lambda: []
    p = Script(**{**HAPPY, "telegram": False, "link": False, "joint_mask": "1111", "personal_mask": "2222"})
    wizard.run(p, deps)
    cfg = json.loads((deps.root / ".data" / "alert.json").read_text())
    assert (cfg["joint_mask"], cfg["personal_mask"], cfg["credit_card_masks"]) == ("1111", "2222", [])


@pytest.mark.parametrize("day,today,expected", [
    (2, date(2026, 11, 20), "2026-12-02"), (25, date(2026, 11, 20), "2026-11-25"), (20, date(2026, 11, 20), "2026-11-20"),
    (31, date(2026, 11, 20), "2026-11-30"), (2, date(2026, 12, 20), "2027-01-02"), (30, date(2027, 1, 31), "2027-02-28"),
])
def test_next_monthly_date(day, today, expected):
    assert next_monthly_date(day, today).isoformat() == expected


def test_update_env_replaces_adds_and_keeps_other_lines(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text("# keep me\nA=1\nB=2\n")
    update_env(f, {"B": "20", "C": "3"})
    assert f.read_text() == "# keep me\nA=1\nB=20\nC=3\n" and stat.S_IMODE(f.stat().st_mode) == 0o600
    assert os.environ["C"] == "3"
    monkeypatch.delenv("B"), monkeypatch.delenv("C")
