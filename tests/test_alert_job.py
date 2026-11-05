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
    """Stands in for whichever channel build_notifier would pick."""
    sent: list[str] = []

    def send(self, message):
        FakeTwilio.sent.append(message)

    def send_tiered(self, messages, levels=None):
        FakeTwilio.tiers = (messages, levels)
        FakeTwilio.sent.append(messages["minimal"])


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    FakeTwilio.sent = []
    monkeypatch.setattr(job, "build_notifier", lambda settings, channel, levels=None: FakeTwilio())


def test_dry_run_prints_and_does_not_send(tmp_path, capsys):
    bill = {"name": "Rent", "amount": 1800, "due": str(date.today() + timedelta(days=2))}
    path = write_cfg(tmp_path, [bill])
    assert job.main(["--config", path, "--joint", "1500", "--personal", "4200"]) == 0
    assert "[dry run, not sent" in capsys.readouterr().out
    assert FakeTwilio.sent == []
    assert not (tmp_path / ".data" / "alert_state.json").exists()
    log = (tmp_path / ".data" / "alerts_log.csv").read_text().splitlines()
    assert log[0].endswith("partner_asked") and ",low,1300.0,True,False," in log[1]


def test_send_texts_once_per_day_per_situation(tmp_path, capsys):
    path = write_cfg(tmp_path, [{"name": "Rent", "amount": 1800, "due": str(date.today() + timedelta(days=2))}])
    job.main(["--config", path, "--joint", "1500", "--personal", "4200", "--send"])
    job.main(["--config", path, "--joint", "1500", "--personal", "4200", "--send"])
    assert len(FakeTwilio.sent) == 1 and FakeTwilio.sent[0].startswith("UFO: Joint may run short before")
    assert "$" not in FakeTwilio.sent[0] and "1,500" not in FakeTwilio.sent[0] and "1,300" not in FakeTwilio.sent[0]  # nothing sensitive leaves
    full = (tmp_path / ".data" / "last_alert.txt").read_text()
    assert "Move $1,300.00 from Personal to Joint" in full  # the detail stays local
    assert "Already alerted" in capsys.readouterr().out
    job.main(["--config", path, "--joint", "1400", "--personal", "4200", "--send"])  # worse: different shortfall, so alert again
    assert len(FakeTwilio.sent) == 2


def test_ok_balance_sends_nothing(tmp_path):
    path = write_cfg(tmp_path, [])
    job.main(["--config", path, "--joint", "5000", "--personal", "4200", "--send"])
    assert FakeTwilio.sent == []


def test_detection_failure_falls_back_to_manual_bills_and_says_so(tmp_path, monkeypatch, capsys):
    path = write_cfg(tmp_path, [{"name": "Rent", "amount": 1800, "due": str(date.today() + timedelta(days=2))}])
    cfg = json.loads(open(path).read())
    cfg["detect_bills"] = True
    open(path, "w").write(json.dumps(cfg))
    monkeypatch.setattr(job, "get_balances", lambda s, items, masks: {"1234": ("Joint", 1500.0), "5678": ("Personal", 4200.0)})

    from ufo.treasury.bills import load_config

    def fake_collect(settings, items, cfg, today):
        return load_config(path).bills, [], ["rent detection: Plaid could not return recurring transactions (PRODUCT_NOT_READY)."]

    monkeypatch.setattr(job, "collect_bills", fake_collect)
    monkeypatch.setattr(job, "load_items", lambda: [])
    job.main(["--config", path, "--send"])
    out = capsys.readouterr()
    assert "Bill detection problem" in out.err
    assert "Some bills could not be checked" in FakeTwilio.sent[0]  # said in the minimal message too
    assert "Some bills could not be detected" in (tmp_path / ".data" / "last_alert.txt").read_text()


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


def test_a_dead_bank_connection_prints_a_plain_message_and_exits_nonzero(tmp_path, capsys, monkeypatch):
    path = write_cfg(tmp_path, [])

    def dead(settings, items, masks):
        raise RuntimeError("Your bank connection needs to be refreshed (Chase asked you to sign in again). Run `python -m ufo.setup`.")

    monkeypatch.setattr(job, "get_balances", dead)
    monkeypatch.setattr(job, "load_items", lambda: [])
    assert job.main(["--config", path]) == 2
    err = capsys.readouterr().err
    assert "Could not read your balances" in err and "sign in again" in err and "Traceback" not in err


# ---- on-demand report and look-ahead override
def test_report_sends_a_covered_message_even_though_everything_is_fine(tmp_path):
    path = write_cfg(tmp_path, [])
    job.main(["--config", path, "--joint", "5000", "--personal", "4200", "--send"])
    assert FakeTwilio.sent == []  # normal behaviour: silence when all is well
    job.main(["--config", path, "--joint", "5000", "--personal", "4200", "--send", "--report"])
    assert len(FakeTwilio.sent) == 1 and FakeTwilio.sent[0].startswith("UFO: Joint is covered through")
    assert "$" not in FakeTwilio.sent[0]


def test_report_ignores_the_once_a_day_limit_and_does_not_use_it_up(tmp_path):
    path = write_cfg(tmp_path, [{"name": "Rent", "amount": 1800, "due": str(date.today() + timedelta(days=2))}])
    args = ["--config", path, "--joint", "1500", "--personal", "4200", "--send"]
    job.main(args)  # the regular alert sends once...
    job.main(args)  # ...and is not repeated
    assert len(FakeTwilio.sent) == 1
    job.main([*args, "--report"])
    job.main([*args, "--report"])
    assert len(FakeTwilio.sent) == 3  # reports always go out


def test_a_report_does_not_suppress_the_regular_scheduled_message(tmp_path):
    path = write_cfg(tmp_path, [{"name": "Rent", "amount": 1800, "due": str(date.today() + timedelta(days=2))}])
    args = ["--config", path, "--joint", "1500", "--personal", "4200", "--send"]
    job.main([*args, "--report"])
    assert not (tmp_path / ".data" / "alert_state.json").exists()
    job.main(args)
    assert len(FakeTwilio.sent) == 2


def test_report_without_send_is_a_dry_run(tmp_path, capsys):
    job.main(["--config", write_cfg(tmp_path, []), "--joint", "5000", "--personal", "4200", "--report"])
    assert FakeTwilio.sent == [] and "[dry run, not sent" in capsys.readouterr().out


def test_through_eom_extends_the_window_to_the_end_of_the_month(tmp_path):
    import calendar

    today = date.today()
    eom = today.replace(day=calendar.monthrange(today.year, today.month)[1])
    path = write_cfg(tmp_path, [])
    job.main(["--config", path, "--joint", "5000", "--personal", "4200", "--send", "--report", "--through", "eom"])
    assert FakeTwilio.sent[0].startswith(f"UFO: Joint is covered through {eom:%b} {eom.day:02d}")


def test_through_counts_bills_inside_the_longer_window(tmp_path):
    due = date.today() + timedelta(days=25)
    path = write_cfg(tmp_path, [{"name": "Big bill", "amount": 4800, "due": str(due)}])  # beyond the 10-day default window
    job.main(["--config", path, "--joint", "5000", "--personal", "4200", "--send"])
    assert FakeTwilio.sent == []  # not looked at yet
    job.main(["--config", path, "--joint", "5000", "--personal", "4200", "--send", "--through", str(due)])
    assert FakeTwilio.sent and FakeTwilio.sent[0].startswith("UFO: Joint may run short")


def test_through_rejects_a_past_or_invalid_date(tmp_path):
    path = write_cfg(tmp_path, [])
    for bad in (str(date.today() - timedelta(days=1)), "soon"):
        with pytest.raises(SystemExit):
            job.main(["--config", path, "--joint", "5000", "--personal", "4200", "--through", bad])
