"""Scheduled run of the alert as a macOS launch agent (launchd): weekly by default, or daily.
It runs `python -m jobs.check_balance --send` at the chosen time.

launchd runs a job that was missed while the Mac slept as soon as it wakes. The job reads secrets from .env in the project
folder at run time, so nothing secret is written into the launch agent file.
"""
from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from pathlib import Path
from typing import Callable

LABEL = "com.ufo.daily-check"


def plist_path(home: Path | None = None) -> Path:
    return (home or Path.home()) / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def parse_time(text: str) -> tuple[int, int]:
    """'8', '8:30', '08:30' -> (8, 30)."""
    h, _, m = text.strip().partition(":")
    hour, minute = int(h), int(m or 0)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("Time must be between 00:00 and 23:59.")
    return hour, minute


WEEKDAYS = {"sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6}


def parse_weekday(text: str | None) -> int | None:
    """'mon' / 'Monday' -> 1 (launchd: 0 = Sunday); 'daily' or empty -> None (every day)."""
    t = (text or "").strip().lower()
    if t in ("", "daily", "day", "every day"):
        return None
    if t[:3] not in WEEKDAYS:
        raise ValueError("Use a weekday like mon or friday, or daily.")
    return WEEKDAYS[t[:3]]


def describe(weekday: int | None, hour: int, minute: int) -> str:
    names = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
    return f"every {names[weekday]} at {hour:02d}:{minute:02d}" if weekday is not None else f"every day at {hour:02d}:{minute:02d}"


def render_plist(root: Path, python: str, hour: int, minute: int, weekday: int | None = None) -> bytes:
    when = {"Hour": hour, "Minute": minute, **({"Weekday": weekday} if weekday is not None else {})}
    return plistlib.dumps({
        "Label": LABEL,
        "ProgramArguments": [python, "-m", "jobs.check_balance", "--send"],
        "WorkingDirectory": str(root),
        "StartCalendarInterval": when,
        "StandardOutPath": str(root / ".data" / "daily.log"),
        "StandardErrorPath": str(root / ".data" / "daily.log"),
        "RunAtLoad": False,
    })


Run = Callable[..., subprocess.CompletedProcess]


def install(root: Path, hour: int, minute: int, weekday: int | None = None, python: str | None = None, home: Path | None = None,
            uid: int | None = None, run: Run = subprocess.run) -> list[str]:
    uid = os.getuid() if uid is None else uid
    py = python or str(root / ".venv" / "bin" / "python")
    if not Path(py).exists() and python is None:
        py = sys.executable
    path = plist_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    (root / ".data").mkdir(exist_ok=True)
    path.write_bytes(render_plist(root, py, hour, minute, weekday))
    os.chmod(path, 0o644)
    run(["launchctl", "bootout", f"gui/{uid}/{LABEL}"], capture_output=True)  # replace an older copy; fine if there is none
    r = run(["launchctl", "bootstrap", f"gui/{uid}", str(path)], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"launchctl could not load the schedule: {(r.stderr or r.stdout).strip()}")
    return [f"Scheduled: {describe(weekday, hour, minute)}. Output goes to {root / '.data' / 'daily.log'}.",
            "If the Mac is asleep at that time, it runs when the Mac wakes."]


def uninstall(home: Path | None = None, uid: int | None = None, run: Run = subprocess.run) -> list[str]:
    uid = os.getuid() if uid is None else uid
    run(["launchctl", "bootout", f"gui/{uid}/{LABEL}"], capture_output=True)
    path = plist_path(home)
    if path.exists():
        path.unlink()
    return ["Daily schedule removed."]


def status(home: Path | None = None, uid: int | None = None, run: Run = subprocess.run) -> str:
    uid = os.getuid() if uid is None else uid
    if not plist_path(home).exists():
        return "No daily schedule is installed."
    r = run(["launchctl", "print", f"gui/{uid}/{LABEL}"], capture_output=True, text=True)
    return "Installed and loaded." if r.returncode == 0 else "Installed but not loaded (run scripts/schedule_daily.py to reload)."


def run_now(uid: int | None = None, run: Run = subprocess.run) -> None:
    """Start the scheduled job immediately (for a first test)."""
    uid = os.getuid() if uid is None else uid
    run(["launchctl", "kickstart", f"gui/{uid}/{LABEL}"], check=True)
