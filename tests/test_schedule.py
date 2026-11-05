import plistlib
import subprocess

import pytest

from ufo.setup import schedule
from ufo.setup.schedule import LABEL, install, parse_time, render_plist, status, uninstall


def test_the_launch_agent_runs_the_send_job_daily_from_the_project_folder(tmp_path):
    d = plistlib.loads(render_plist(tmp_path, "/proj/.venv/bin/python", 8, 5))
    assert d["Label"] == LABEL
    assert d["ProgramArguments"] == ["/proj/.venv/bin/python", "-m", "jobs.check_balance", "--send"]
    assert d["WorkingDirectory"] == str(tmp_path) and d["StartCalendarInterval"] == {"Hour": 8, "Minute": 5}
    assert d["StandardOutPath"] == str(tmp_path / ".data" / "daily.log") and d["RunAtLoad"] is False


def test_no_secrets_are_written_into_the_launch_agent(tmp_path):
    (tmp_path / ".env").write_text("PLAID_SECRET=very-secret\nTELEGRAM_BOT_TOKEN=123:tok\n")
    raw = render_plist(tmp_path, "/p/python", 8, 0).decode()
    assert "very-secret" not in raw and "123:tok" not in raw and "PLAID" not in raw  # the job reads .env itself at run time


@pytest.mark.parametrize("text,expected", [("8", (8, 0)), ("08:00", (8, 0)), ("7:30", (7, 30)), (" 23:59 ", (23, 59))])
def test_parse_time(text, expected):
    assert parse_time(text) == expected


@pytest.mark.parametrize("bad", ["24:00", "8:60", "-1", "abc", ""])
def test_parse_time_rejects_nonsense(bad):
    with pytest.raises(ValueError):
        parse_time(bad)


class FakeRun:
    def __init__(self, fail_bootstrap=False):
        self.calls, self.fail = [], fail_bootstrap

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        bad = self.fail and cmd[1] == "bootstrap"
        return subprocess.CompletedProcess(cmd, 1 if bad else 0, stdout="", stderr="boom" if bad else "")


def test_install_writes_the_agent_replaces_an_old_one_and_loads_it(tmp_path):
    root, home, run = tmp_path / "proj", tmp_path / "home", FakeRun()
    root.mkdir()
    lines = install(root, 8, 0, python="/proj/.venv/bin/python", home=home, uid=501, run=run)
    path = home / "Library" / "LaunchAgents" / f"{LABEL}.plist"
    assert path.exists() and oct(path.stat().st_mode & 0o777) == "0o644"
    assert run.calls == [["launchctl", "bootout", f"gui/501/{LABEL}"], ["launchctl", "bootstrap", "gui/501", str(path)]]
    assert "08:00" in lines[0] and (root / ".data").is_dir()


def test_a_failed_load_raises_a_clear_error(tmp_path):
    with pytest.raises(RuntimeError, match="could not load the schedule: boom"):
        install(tmp_path, 8, 0, python="/p/python", home=tmp_path / "h", uid=1, run=FakeRun(fail_bootstrap=True))


def test_uninstall_and_status(tmp_path):
    home, run = tmp_path / "h", FakeRun()
    assert status(home=home, uid=1, run=run) == "No daily schedule is installed."
    install(tmp_path, 8, 0, python="/p/python", home=home, uid=1, run=run)
    assert status(home=home, uid=1, run=run) == "Installed and loaded."
    uninstall(home=home, uid=1, run=run)
    assert not schedule.plist_path(home).exists() and status(home=home, uid=1, run=run).startswith("No daily")


# ---- wizard step
from tests.test_wizard import HAPPY, Script, deps  # noqa: E402,F401
from ufo.setup import wizard  # noqa: E402


def test_the_wizard_offers_to_schedule_and_installs_at_the_chosen_time(deps):  # noqa: F811
    got = []
    deps.install_schedule = lambda root, h, m: got.append((root, h, m)) or [f"Scheduled {h:02d}:{m:02d}"]
    deps.schedule_installed = lambda: False
    p = Script(**{**HAPPY, "telegram": False, "schedule": True, "schedule_time": "7:30"})
    wizard.run(p, deps)
    assert got == [(deps.root, 7, 30)] and "Scheduled 07:30" in p.output


def test_a_bad_time_is_asked_again_and_declining_installs_nothing(deps):  # noqa: F811
    got = []
    deps.install_schedule = lambda root, h, m: got.append((h, m)) or []
    deps.schedule_installed = lambda: False
    wizard.run(Script(**{**HAPPY, "telegram": False, "schedule": True, "schedule_time": ["25:99", "6:00"]}), deps)
    assert got == [(6, 0)]
    got.clear()
    wizard.run(Script(**{**HAPPY, "telegram": False, "schedule": False}), deps)
    assert got == []


def test_an_existing_schedule_is_left_alone_unless_you_ask_to_change_it(deps):  # noqa: F811
    got = []
    deps.install_schedule = lambda root, h, m: got.append((h, m)) or []
    deps.schedule_installed = lambda: True
    p = Script(**{**HAPPY, "telegram": False, "schedule_redo": False})
    wizard.run(p, deps)
    assert got == [] and "already scheduled" in p.output


def test_non_mac_systems_get_a_pointer_to_cron(deps):  # noqa: F811
    deps.install_schedule = None
    p = Script(**{**HAPPY, "telegram": False})
    wizard.run(p, deps)
    assert "cron" in p.output
