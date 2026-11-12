# The event model every importer emits

Importers (`src/ufo/importers/`) turn one brokerage's files into `ufo.performance.events.Event` rows. The ledger,
metrics and reports never see a file format. Read-only: importers read files you downloaded; none talks to a brokerage.

## Interface
```python
class Importer(Protocol):
    name: str
    def parse(self, files: list[str], account_digits: str = "") -> ParsedHistory: ...
    def positions(self, files: list[str], account_digits: str = "") -> list[Snapshot]: ...
```
Register with `ufo.importers.register(MyImporter())`. The account registry (`.data/accounts.json`) refers to an importer by `name`.

## Event fields
| field | meaning |
|---|---|
| `when`, `seq` | date; position within the day, oldest first |
| `kind` | `buy`, `sell`, `contribution` (external in), `withdrawal` (external out), `dividend`, `interest`, `fee`, `reinvestment` (internal), `split` |
| `symbol`, `quantity`, `price`, `fees` | as in the file; sells have negative quantity |
| `amount` | cash effect on the account (money in positive) |
| `in_kind` | shares moved rather than cash; `amount` must be the market value on the date |
| `cash_balance` | the brokerage's running cash balance after the row, if it gives one |
| `account_id` | registry id of the account (filled by the runner) |
| `source` | importer name |
| `transfer_hint` | the importer knows this contribution/withdrawal is a move between household accounts |

Rules: only `contribution` and `withdrawal` cross the account boundary (`external_flow`). Unrecognized rows become
warnings, never silent drops. `transfer_hint` does **not** change `external_flow`: for one account alone a transfer is
still a deposit or withdrawal. The combined view (issue 102) nets transfers out across accounts, using the hint as a
hint only (cash transfers may carry none).

`Snapshot(when, quantities, value)`: shares per symbol on a date and, when the file has it, the account total for reconciliation.

Information, not investment advice.
