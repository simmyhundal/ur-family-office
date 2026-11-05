import json
from datetime import date, timedelta

import pytest

from jobs import check_balance as job
from ufo.providers.plaid_client import pick_checking_balance


def write_cfg(tmp_path, bills):
    (tmp_path / ".data").mkdir()
    p = tmp_path / ".data" / "alert.json"
    p.write_text(json.dumps({"cushion": 1000, "next_topup": str(date.today() + timedelta(days=10)), "bills": bills}))
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
    assert job.main(["--config", path, "--balance", "1500"]) == 0
    assert "[dry run, not sent]" in capsys.readouterr().out
    assert FakeTwilio.sent == []
    assert not (tmp_path / ".data" / "alert_state.json").exists()
    assert "False" in (tmp_path / ".data" / "alerts_log.csv").read_text().splitlines()[1]


def test_send_texts_once_per_day_per_situation(tmp_path, capsys):
    path = write_cfg(tmp_path, [{"name": "Rent", "amount": 1800, "due": str(date.today() + timedelta(days=2))}])
    job.main(["--config", path, "--balance", "1500", "--send"])
    job.main(["--config", path, "--balance", "1500", "--send"])
    assert len(FakeTwilio.sent) == 1 and "UFO: checking is $1,500.00" in FakeTwilio.sent[0]
    assert "Already alerted" in capsys.readouterr().out
    job.main(["--config", path, "--balance", "1400", "--send"])  # worse: different shortfall, so alert again
    assert len(FakeTwilio.sent) == 2


def test_ok_balance_sends_nothing(tmp_path):
    path = write_cfg(tmp_path, [])
    job.main(["--config", path, "--balance", "5000", "--send"])
    assert FakeTwilio.sent == []


def test_pick_checking_balance():
    accts = [
        {"name": "Chase Savings", "mask": "1111", "subtype": "savings", "balances": {"available": 9000, "current": 9000}},
        {"name": "Chase Checking", "mask": "2222", "subtype": "checking", "balances": {"available": None, "current": 1234.5}},
    ]
    assert pick_checking_balance(accts) == ("Chase Checking …2222", 1234.5)  # falls back to current
    accts[1]["balances"]["available"] = 1000.0
    assert pick_checking_balance(accts, "2222") == ("Chase Checking …2222", 1000.0)
    with pytest.raises(ValueError, match="No checking"):
        pick_checking_balance(accts, "9999")
    accts.append({**accts[1], "mask": "3333"})
    with pytest.raises(ValueError, match="account_mask"):
        pick_checking_balance(accts)
