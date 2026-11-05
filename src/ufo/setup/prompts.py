"""Terminal prompts behind a small interface so the wizard can be tested with scripted answers."""
from __future__ import annotations

import getpass
from typing import Protocol, Sequence


class Prompter(Protocol):
    def say(self, text: str = "") -> None: ...
    def ask(self, key: str, text: str, default: str | None = None) -> str: ...
    def secret(self, key: str, text: str) -> str: ...
    def confirm(self, key: str, text: str, default: bool = True) -> bool: ...
    def choose(self, key: str, text: str, options: Sequence[str]) -> int: ...
    def choose_many(self, key: str, text: str, options: Sequence[str]) -> list[int]: ...


class TerminalPrompter:
    def say(self, text: str = "") -> None:
        print(text)

    def ask(self, key: str, text: str, default: str | None = None) -> str:
        suffix = f" [{default}]" if default is not None else ""
        while True:
            v = input(f"{text}{suffix}: ").strip()
            if v:
                return v
            if default is not None:
                return default

    def secret(self, key: str, text: str) -> str:
        return getpass.getpass(f"{text} (input hidden): ").strip()

    def confirm(self, key: str, text: str, default: bool = True) -> bool:
        hint = "Y/n" if default else "y/N"
        v = input(f"{text} [{hint}]: ").strip().lower()
        return default if not v else v in ("y", "yes")

    def choose(self, key: str, text: str, options: Sequence[str]) -> int:
        print(text)
        for i, o in enumerate(options, 1):
            print(f"  {i}. {o}")
        while True:
            v = input("Number: ").strip()
            if v.isdigit() and 1 <= int(v) <= len(options):
                return int(v) - 1

    def choose_many(self, key: str, text: str, options: Sequence[str]) -> list[int]:
        print(text)
        for i, o in enumerate(options, 1):
            print(f"  {i}. {o}")
        while True:
            v = input("Numbers separated by commas (Enter for none): ").strip()
            if not v:
                return []
            try:
                picks = sorted({int(x) - 1 for x in v.split(",")})
            except ValueError:
                continue
            if all(0 <= p < len(options) for p in picks):
                return picks
