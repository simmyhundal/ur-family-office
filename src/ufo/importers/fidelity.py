"""The Fidelity importer: activity-history and positions CSVs -> neutral events and snapshots."""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from ufo.importers import register
from ufo.performance.events import ParsedHistory, merge_histories, split_by_account
from ufo.performance.ledger import Snapshot
from ufo.providers.fidelity_csv import parse_fidelity_positions
from ufo.providers.fidelity_history import parse_fidelity_history


def _snapshot_date(path: str):
    m = re.search(r"([A-Z][a-z]{2}-\d\d-\d{4})", path)
    return datetime.strptime(m.group(1), "%b-%d-%Y").date() if m else None


class FidelityImporter:
    name = "fidelity"

    def parse(self, files: list[str], account_digits: str = "") -> ParsedHistory:
        parts = [parse_fidelity_history(Path(f).read_text(encoding="utf-8-sig")) for f in sorted(files)]
        hist = merge_histories(parts)
        for e in hist.events:
            e.source = self.name
        if account_digits and any(e.account_ref for e in hist.events):  # an export that holds several accounts
            hist = split_by_account(hist, account_digits)
        return hist

    def positions(self, files: list[str], account_digits: str = "") -> list[Snapshot]:
        out = []
        for f in sorted(files):
            d = _snapshot_date(f)
            if not d:
                continue
            holdings, _ = parse_fidelity_positions(Path(f).read_text(encoding="utf-8-sig"))
            mine = [h for h in holdings if account_digits in f"{h['account']}{h['account_mask']}"]
            if not mine:
                continue
            out.append(Snapshot(when=d, quantities={h["symbol"]: h["quantity"] for h in mine if not h["is_cash"]},
                                value=sum(h["value"] or 0.0 for h in mine)))
        return out


register(FidelityImporter())
