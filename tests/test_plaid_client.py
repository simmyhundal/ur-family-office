"""Every Plaid-facing function is run against a fake client, so a typo or a missing helper fails here instead of during setup."""
import shutil
import subprocess
import sys

import pytest

from ufo.config import Settings
from ufo.providers import plaid_client as pc


class Enum:
    def __init__(self, value):
        self.value = value


class Model:
    """Mimics a Plaid SDK model: subscriptable and has to_dict()."""

    def __init__(self, d):
        self._d = d

    def to_dict(self):
        return self._d

    def __getitem__(self, k):
        return self._d[k]


ACCOUNTS = [
    Model({"account_id": "a1", "name": "Joint Checking", "mask": "4821", "type": Enum("depository"), "subtype": Enum("checking"),
           "balances": {"available": 900.0, "current": 950.0}}),
    Model({"account_id": "a2", "name": "Personal Checking", "mask": "7390", "type": Enum("depository"), "subtype": Enum("checking"),
           "balances": {"available": None, "current": 4321.5}}),
    Model({"account_id": "a3", "name": "Freedom", "mask": "9999", "type": Enum("credit"), "subtype": Enum("credit card"),
           "balances": {"available": 5000.0, "current": 2100.5}}),
]


class FakeClient:
    def accounts_get(self, req):
        return {"accounts": ACCOUNTS}

    def accounts_balance_get(self, req):
        return {"accounts": ACCOUNTS}

    def transactions_recurring_get(self, req):
        assert req.account_ids == ["a1"]
        return {"outflow_streams": [Model({"merchant_name": "Landlord", "frequency": "MONTHLY"})]}

    def liabilities_get(self, req):
        assert req.options.account_ids == ["a3"]
        return {"liabilities": Model({"credit": [{"account_id": "a3", "next_payment_due_date": "2026-12-01", "minimum_payment_amount": 40.0,
                                                  "last_statement_balance": 2100.5, "is_overdue": False}]})}


@pytest.fixture(autouse=True)
def fake(monkeypatch):
    monkeypatch.setattr(pc, "make_client", lambda s: FakeClient())


S = Settings()
ITEMS = [{"item_id": "i", "access_token": "tok"}]


def test_list_accounts_flattens_plaid_enums_and_returns_no_balances():
    out = pc.list_accounts(S, ITEMS)
    assert out[0] == {"name": "Joint Checking", "mask": "4821", "type": "depository", "subtype": "checking"}
    assert out[2]["type"] == "credit" and all("balances" not in a for a in out)


def test_get_balances_by_mask_uses_available_then_current():
    b = pc.get_balances(S, ITEMS, ["4821", "7390"])
    assert b == {"4821": ("Joint Checking …4821", 900.0), "7390": ("Personal Checking …7390", 4321.5)}


def test_recurring_outflows_for_the_joint_account():
    assert pc.get_recurring_outflows(S, ITEMS, "4821") == [{"merchant_name": "Landlord", "frequency": "MONTHLY"}]
    with pytest.raises(RuntimeError, match="No linked account"):
        pc.get_recurring_outflows(S, ITEMS, "0000")


def test_credit_card_liabilities_by_mask():
    cards = pc.get_credit_card_liabilities(S, ITEMS, ["9999"])
    assert cards == [{"name": "Freedom", "mask": "9999", "next_payment_due_date": "2026-12-01", "minimum_payment_amount": 40.0,
                      "last_statement_balance": 2100.5, "is_overdue": False}]
    with pytest.raises(RuntimeError, match="No credit card found"):
        pc.get_credit_card_liabilities(S, ITEMS, ["9999", "1234"])


def test_no_undefined_names_anywhere():
    """A missing helper is a crash waiting for the first real run. Lint for undefined names across the code."""
    if not shutil.which("ruff") and subprocess.run([sys.executable, "-m", "ruff", "--version"], capture_output=True).returncode != 0:
        pytest.skip("ruff not installed")
    r = subprocess.run([sys.executable, "-m", "ruff", "check", "--select", "F821,F811", "--output-format", "concise", "src", "jobs", "scripts"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout
