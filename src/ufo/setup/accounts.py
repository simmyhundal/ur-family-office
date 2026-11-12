"""`python -m ufo.setup accounts`: list, add, edit and remove investment accounts in .data/accounts.json."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from .. import importers
from ..accounts.registry import (Account, EndValue, Registry, RegistryError, Source, Wrapper,
                                 load_registry, missing_files, registry_path, save_registry)
from .prompts import Prompter

MAX_ROUNDS = 50  # loops are capped so a missing scripted answer can never hang
MAX_TRIES = 5
WRAPPERS = list(Wrapper)


def _date(p: Prompter, key: str, text: str, default: str | None = None) -> date | None:
    for _ in range(MAX_TRIES):
        raw = p.ask(key, text + " (YYYY-MM-DD, or - for none)", default or "-")
        if raw.strip() in ("-", ""):
            return None
        try:
            return date.fromisoformat(raw.strip())
        except ValueError:
            p.say("Please write the date as YYYY-MM-DD.")
    raise RegistryError(f"Could not read a date for: {text}")


def describe(a: Account) -> str:
    state = f"closed {a.closed}" if a.closed else "open"
    return f"{a.id}: {a.label} ({a.brokerage}, {a.wrapper.value}, owner {a.owner}, {state})"


def list_accounts(p: Prompter, reg: Registry, root: Path) -> None:
    if not reg.accounts:
        p.say("No accounts yet.")
    for a in reg.accounts:
        p.say(describe(a))
        for m in missing_files(a, root):
            p.say(f"  ! {m}")


def ask_account(p: Prompter, existing: Account | None = None, taken: set[str] = frozenset()) -> Account:
    e = existing
    for _ in range(MAX_TRIES):
        label = p.ask("label", "Name for this account", e.label if e else None)
        aid = p.ask("id", "Short id (letters, digits, - or _)", e.id if e else label.lower().replace(" ", "-"))
        if aid in taken and not (e and e.id == aid):
            p.say(f"The id {aid!r} is already used.")
            continue
        brokerages = sorted(importers.names())
        b = brokerages[p.choose("brokerage", "Brokerage", brokerages)]
        w = WRAPPERS[p.choose("wrapper", "Account type", [x.value for x in WRAPPERS])]
        digits = p.ask("digits", "Last digits (kept on this Mac only; - for none)", e.last_digits if e and e.last_digits else "-")
        owner = p.ask("owner", "Owner (free text, e.g. owner, partner, joint)", e.owner if e else "owner")
        opened = _date(p, "opened", "Opened", str(e.opened) if e and e.opened else None)
        closed = _date(p, "closed", "Closed", str(e.closed) if e and e.closed else None)
        hist = p.ask("history_glob", "History files (a glob, relative to the project folder)", e.source.history_glob if e else None)
        snap = p.ask("snapshot_glob", "Positions snapshot files (glob, - for none)", e.source.snapshot_glob or "-" if e else "-")
        ev: EndValue | None = None
        if p.choose("end_kind", "How is the ending value supplied?", ["Statement value with a date", "Computed from a positions snapshot"]) == 0:
            raw = p.ask("end_value", "Statement value in dollars").replace("$", "").replace(",", "")
            as_of = _date(p, "end_as_of", "Statement date")
            try:
                ev = EndValue(kind="statement", value=float(raw), as_of=as_of)
            except (ValueError, TypeError):
                p.say("That statement value or date did not look right.")
                continue
        else:
            ev = EndValue(kind="snapshot")
        try:
            return Account(id=aid, label=label, brokerage=b, last_digits="" if digits == "-" else digits, wrapper=w,
                           owner=owner, opened=opened, closed=closed, ending_value=ev,
                           source=Source(importer=b, history_glob=hist, snapshot_glob="" if snap == "-" else snap))
        except ValueError as err:
            p.say(f"Could not save that account: {err}")
    raise RegistryError("Too many attempts; nothing was saved.")


def run(p: Prompter, root: Path | None = None) -> None:
    root = root or Path.cwd()
    path = registry_path(root)
    try:
        reg = load_registry(path)
    except RegistryError as e:
        p.say(str(e))
        return
    for _ in range(MAX_ROUNDS):
        list_accounts(p, reg, root)
        pick = p.choose("action", "What next?", ["Done", "Add an account", "Edit an account", "Remove an account"])
        if pick == 0:
            return
        try:
            if pick == 1:
                reg = Registry(accounts=reg.accounts + [ask_account(p, taken={a.id for a in reg.accounts})])
            elif reg.accounts:
                i = p.choose("which", "Which account?", [describe(a) for a in reg.accounts])
                if pick == 3:
                    reg = Registry(accounts=[a for j, a in enumerate(reg.accounts) if j != i])
                else:
                    cur = reg.accounts[i]
                    new = ask_account(p, cur, {a.id for a in reg.accounts})
                    reg = Registry(accounts=[new if j == i else a for j, a in enumerate(reg.accounts)])
            else:
                p.say("No accounts yet.")
                continue
        except (RegistryError, ValueError) as e:
            p.say(str(e))
            continue
        save_registry(path, reg)
        p.say(f"Saved {path}.")
