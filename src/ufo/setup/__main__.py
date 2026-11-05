import sys

from . import schedule
from .prompts import TerminalPrompter
from .wizard import Deps, default_dry_run, mac_copy, mac_open, run

if __name__ == "__main__":
    mac = sys.platform == "darwin"
    deps = Deps(
        run_dry_run=default_dry_run, open_url=mac_open, copy=mac_copy,
        install_schedule=(lambda root, h, m: schedule.install(root, h, m)) if mac else None,
        schedule_installed=(lambda: schedule.plist_path().exists()) if mac else None,
    )
    try:
        run(TerminalPrompter(), deps)
    except (KeyboardInterrupt, EOFError):
        print("\nSetup cancelled. Nothing else was changed; run it again any time.")
