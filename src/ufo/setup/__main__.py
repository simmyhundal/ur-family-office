import sys

from . import schedule
from .prompts import TerminalPrompter
from .wizard import Deps, default_dry_run, mac_copy, mac_open, run

if __name__ == "__main__":
    try:
        if sys.argv[1:2] == ["accounts"]:
            from . import accounts
            accounts.run(TerminalPrompter())
            raise SystemExit(0)
        mac = sys.platform == "darwin"
        deps = Deps(
            run_dry_run=default_dry_run, open_url=mac_open, copy=mac_copy,
            install_schedule=(lambda root, h, m, wd: schedule.install(root, h, m, wd)) if mac else None,
            schedule_installed=(lambda: schedule.plist_path().exists()) if mac else None,
        )
        run(TerminalPrompter(), deps)
    except (KeyboardInterrupt, EOFError):
        print("\nSetup cancelled. Nothing else was changed; run it again any time.")
