"""Small, safe .env updater: keeps other lines and comments, never echoes values, file is owner-only."""
from __future__ import annotations

import os
from pathlib import Path


def update_env(path: str | Path, updates: dict[str, str]) -> None:
    p = Path(path)
    lines = p.read_text().splitlines() if p.exists() else []
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else None
        if key in updates:
            out.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            out.append(line)
    out += [f"{k}={v}" for k, v in updates.items() if k not in seen]
    p.write_text("\n".join(out) + "\n")
    os.chmod(p, 0o600)
    for k, v in updates.items():  # make the new values visible to the rest of this run
        os.environ[k] = v
