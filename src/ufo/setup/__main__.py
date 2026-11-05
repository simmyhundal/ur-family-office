from .prompts import TerminalPrompter
from .wizard import Deps, default_dry_run, run

if __name__ == "__main__":
    try:
        run(TerminalPrompter(), Deps(run_dry_run=default_dry_run))
    except (KeyboardInterrupt, EOFError):
        print("\nSetup cancelled. Nothing else was changed; run it again any time.")
