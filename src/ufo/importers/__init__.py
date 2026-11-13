"""Importers turn one brokerage's files into the neutral event model (docs/event-model.md). Registry by name."""
from __future__ import annotations

from typing import Protocol

from ufo.performance.events import ParsedHistory
from ufo.performance.ledger import Snapshot


class Importer(Protocol):
    name: str

    def parse(self, files: list[str], account_digits: str = "") -> ParsedHistory:
        """Activity history for one account. `account_digits` picks the account when a file holds several."""
        ...

    def positions(self, files: list[str], account_digits: str = "") -> list[Snapshot]:
        """Dated holdings snapshots for one account (empty when the brokerage offers none)."""
        ...


_REGISTRY: dict[str, Importer] = {}


def register(importer: Importer) -> None:
    _REGISTRY[importer.name] = importer


def get(name: str) -> Importer:
    if name not in _REGISTRY:
        raise KeyError(f"unknown importer {name!r}; known: {', '.join(names())}")
    return _REGISTRY[name]


def names() -> set[str]:
    return set(_REGISTRY)


from ufo.importers import acorns, fidelity, manual, voya  # noqa: E402,F401  (register themselves)
