"""The account registry: one local list of the household's investment accounts across brokerages (issue 98).

Lives in `.data/accounts.json` (gitignored, mode 0600). Last digits and statement values are real data and stay
local. Read-only: nothing here talks to a brokerage or moves money.
"""
from __future__ import annotations

import json
import os
from datetime import date
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ValidationError, field_validator, model_validator

# Importers that can read an account's files. Issue 99 replaces this with the real importer registry.
KNOWN_BROKERAGES: set[str] = {"fidelity"}


class RegistryError(Exception):
    """A problem with the registry file or an entry, worded for the person running the command."""


class Wrapper(str, Enum):
    TAXABLE = "taxable"
    TRADITIONAL_IRA = "traditional_ira"
    ROTH_IRA = "roth_ira"
    K401 = "401k"
    HSA = "hsa"
    OTHER = "other"


class Source(BaseModel):
    importer: str  # name of the importer, e.g. "fidelity"
    history_glob: str  # activity-history files, relative to the project folder
    snapshot_glob: str = ""  # positions snapshots (optional)


class EndValue(BaseModel):
    """How the ending value is supplied: a statement figure with its date, or computed from a positions snapshot."""
    kind: str  # "statement" | "snapshot"
    value: float | None = None
    as_of: date | None = None

    @model_validator(mode="after")
    def _check(self) -> "EndValue":
        if self.kind not in ("statement", "snapshot"):
            raise ValueError("ending value kind must be 'statement' or 'snapshot'")
        if self.kind == "statement" and (self.value is None or self.as_of is None):
            raise ValueError("a statement ending value needs both a value and an as-of date")
        return self


class Account(BaseModel):
    id: str
    label: str
    brokerage: str
    last_digits: str = ""  # local only
    wrapper: Wrapper = Wrapper.TAXABLE
    owner: str = "owner"
    opened: date | None = None
    closed: date | None = None
    source: Source
    ending_value: EndValue | None = None

    @field_validator("id")
    @classmethod
    def _slug(cls, v: str) -> str:
        v = v.strip()
        if not v or not all(c.isalnum() or c in "-_" for c in v):
            raise ValueError("id must be letters, digits, - or _")
        return v

    @field_validator("brokerage")
    @classmethod
    def _brokerage(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in KNOWN_BROKERAGES:
            raise ValueError(f"unknown brokerage {v!r}; known: {', '.join(sorted(KNOWN_BROKERAGES))}")
        return v

    @model_validator(mode="after")
    def _dates(self) -> "Account":
        if self.opened and self.closed and self.closed < self.opened:
            raise ValueError("closed date is before the opened date")
        return self

    @property
    def is_closed(self) -> bool:
        return self.closed is not None


class Registry(BaseModel):
    accounts: list[Account] = []

    @model_validator(mode="after")
    def _unique(self) -> "Registry":
        ids = [a.id for a in self.accounts]
        dup = sorted({i for i in ids if ids.count(i) > 1})
        if dup:
            raise ValueError(f"duplicate account id: {', '.join(dup)}")
        return self

    def get(self, account_id: str) -> Account | None:
        return next((a for a in self.accounts if a.id == account_id), None)


def registry_path(root: Path) -> Path:
    return root / ".data" / "accounts.json"


def load_registry(path: Path) -> Registry:
    """A missing file is an empty registry. A bad file raises RegistryError, never a traceback."""
    if not path.exists():
        return Registry()
    try:
        return Registry.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except json.JSONDecodeError as e:
        raise RegistryError(f"{path.name} is not valid JSON (line {e.lineno}). Fix it or move it aside.") from None
    except ValidationError as e:
        first = e.errors()[0]
        where = ".".join(str(x) for x in first["loc"])
        raise RegistryError(f"{path.name} has a problem at {where}: {first['msg']}") from None


def save_registry(path: Path, reg: Registry) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(reg.model_dump_json(indent=2) + "\n")
    os.chmod(path, 0o600)


def missing_files(a: Account, root: Path) -> list[str]:
    """Plain messages for source globs that match nothing."""
    out = []
    if not any(root.glob(a.source.history_glob)):
        out.append(f"{a.label}: no history files match {a.source.history_glob}")
    if a.source.snapshot_glob and not any(root.glob(a.source.snapshot_glob)):
        out.append(f"{a.label}: no snapshot files match {a.source.snapshot_glob}")
    return out
