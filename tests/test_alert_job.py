import json
from datetime import date, timedelta

import pytest

from jobs import check_balance as job
from ufo.providers.plaid_client import pick_account_balance


def write_cfg(tmp_path, bills):
    (tmp_path / ".data").mkdir()
    p = tmp_path / ".data" / "alert.json"
    p.write_text(json.dumps({"cushion": 1000, "next_topup": str(date.today() + timedelta(days=10)), "joint_mask": "1234", "personal_mask": "5678", "personal_floor": 1500, "bills": bills}))
    return str(p)


class FakeTwilio:
    sent: list[str] = []

    def __init__(self, settings):
        pass

    def send(self, message):
        FakeTwilio.sent.append(message)


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    FakeTwilio.sent = []
    monkeypatch.setattr(job, "TwilioNotifier", FakeTwilio)


def test_dry_run_prints_and_does_not_send(tmp_path, capsys):
    bill = {"name": "Rent", "amount": 1800, "due": str(date.today() + timedelta(days=2))}
    path = write_cfg(tmp_path, [bill])
    assert job.main(["--config", path, "--joint", "1500", "--personal", "4200"]) == 0
    assert "[dry run, not sent]" in capsys.readouterr().out
    assert FakeTwilio.sent == []
    assert not (tmp_path / ".data" / "alert_state.json").exists()
    log = (tmp_path / ".data" / "alerts_log.csv").read_text().splitlines()
    assert log[0].endswith("partner_asked") and ",low,1300.0,True,False," in log[1]


def test_send_texts_once_per_day_per_situation(tmp_path, capsys):
    path = write_cfg(tmp_path, [{"name": "Rent", "amount": 1800, "due": str(date.today() + timedelta(days=2))}])
    job.main(["--config", path, "--joint", "1500", "--personal", "4200", "--send"])
    job.main(["--config", path, "--joint", "1500", "--personal", "4200", "--send"])
    assert len(FakeTwilio.sent) == 1 and "UFO: Joint is $1,500.00" in FakeTwilio.sent[0] and "Move $1,300.00 from Personal to Joint" in FakeTwilio.sent[0]
    assert "Already alerted" in capsys.readouterr().out
    job.main(["--config", path, "--joint", "1400", "--personal", "4200", "--send"])  # worse: different shortfall, so alert again
    assert len(FakeTwilio.sent) == 2


def test_ok_balance_sends_nothing(tmp_path):
    path = write_cfg(tmp_path, [])
    job.main(["--config", path, "--joint", "5000", "--personal", "4200", "--send"])
    assert FakeTwilio.sent == []


def test_joint_and_personal_must_be_given_together(tmp_path):
    path = write_cfg(tmp_path, [])
    with pytest.raises(SystemExit):
        job.main(["--config", path, "--joint", "1500"])


def test_pick_account_balance():
    accts = [
        {"name": "Chase Joint", "mask": "1234", "subtype": "checking", "balances": {"available": 900.0, "current": 950.0}},
        {"name": "Chase Personal", "mask": "5678", "subtype": "savings", "balances": {"available": None, "current": 4321.5}},
    ]
    assert pick_account_balance(accts, "1234") == ("Chase Joint …1234", 900.0)
    assert pick_account_balance(accts, "5678") == ("Chase Personal …5678", 4321.5)  # falls back to current
    with pytest.raises(ValueError, match="No linked account"):
        pick_account_balance(accts, "9999")
    with pytest.raises(ValueError, match="Several"):
        pick_account_balance(accts + [{**accts[0]}], "1234")
