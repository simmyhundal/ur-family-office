"""The manual importer: a small local CSV of dated contributions and withdrawals, for accounts with no export
(savings bonds, an annuity). Columns: date (YYYY-MM-DD), kind (contribution|withdrawal), amount, description (optional).
The ending value comes from the registry's statement value. Blank lines and lines starting with # are ignored."""
from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from ufo.importers import register
from ufo.performance.events import Event, Kind, ParsedHistory
from ufo.performance.ledger import Snapshot

KINDS = {"contribution": Kind.CONTRIBUTION, "withdrawal": Kind.WITHDRAWAL}


class ManualImporter:
    name = "manual"

    def parse(self, files: list[str], account_digits: str = "") -> ParsedHistory:
        events: list[Event] = []
        warnings: list[str] = []
        for f in sorted(files):
            lines = [ln for ln in Path(f).read_text(encoding="utf-8-sig").splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
            for n, row in enumerate(csv.DictReader(lines), start=2):
                row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
                try:
                    kind = KINDS[row.get("kind", "").lower()]
                    when = date.fromisoformat(row.get("date", ""))
                    amount = abs(float(row.get("amount", "").replace(",", "").replace("$", "")))
                except (KeyError, ValueError):
                    warnings.append(f"{Path(f).name} row {n}: needs a date (YYYY-MM-DD), a kind (contribution or withdrawal) and an amount; skipped.")
                    continue
                events.append(Event(when=when, kind=kind, amount=amount if kind == Kind.CONTRIBUTION else -amount,
                                    description=row.get("description", ""), seq=len(events), source=self.name))
        events.sort(key=lambda e: (e.when, e.seq))
        return ParsedHistory(events=events, warnings=warnings, first=events[0].when if events else None,
                             last=events[-1].when if events else None)

    def positions(self, files: list[str], account_digits: str = "") -> list[Snapshot]:
        return []


register(ManualImporter())
