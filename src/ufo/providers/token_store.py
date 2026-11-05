"""Plaid access tokens live only in a local, gitignored, owner-only file."""
from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT = Path(".data/items.json")


def load_items(path: Path = DEFAULT) -> list[dict]:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return []


def save_items(items: list[dict], path: Path = DEFAULT) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(json.dumps(items, indent=2))
    os.chmod(path, 0o600)


def save_item(item: dict, path: Path = DEFAULT) -> None:
    items = [i for i in load_items(path) if i.get("item_id") != item["item_id"]] + [item]
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(json.dumps(items, indent=2))
    os.chmod(path, 0o600)
