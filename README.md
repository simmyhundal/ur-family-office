# UFO: Your Family Office

UFO warns you before your checking account runs low, and grows into a full family office for everyday households.
It is being built for one household first; each feature has to earn its place.

## Status
| Area | State |
|---|---|
| Low-balance alert (v1): balance minus bills due soon vs a cushion, text when below | next |
| Withdrawal rebalancer: proposed trades, order tickets | prototyped in `fin-advisor` (Node); port is planned |
| Bill detection from Plaid recurring transactions | planned |
| Tax-lot optimization (HIFO, TLH) | planned; needs per-lot data Plaid does not provide |
| Multi-generational access (roles, delegation) | planned |

v1 is read-only: it cannot move money. UFO gives information and alerts, not financial, tax or legal advice.

## Layout
- `src/ufo/providers/` data in (Plaid, Fidelity CSV, quotes); read-only
- `src/ufo/treasury/` low-balance alert, bills, notifications
- `src/ufo/rebalance/` withdrawal planning and order tickets
- `src/ufo/tax/`, `access/`, `api/`, `store/` later phases
- `jobs/` cron entry points; `scripts/` one-offs (e.g. Plaid link)
- `docs/decisions/` short decision records

## Setup
Needs Python 3.11+.

```bash
python3.11 -m venv .venv && source .venv/bin/activate   # or: uv venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
pytest
```
