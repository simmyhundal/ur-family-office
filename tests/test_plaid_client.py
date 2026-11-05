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


# ---- broken or duplicate bank connections (found on the first live run)
import json as _json  # noqa: E402

import plaid  # noqa: E402


def api_error(code):
    e = plaid.ApiException(status=400, reason="Bad Request")
    e.body = _json.dumps({"error_code": code, "display_message": "x", "error_message": "y"})
    return e


def test_plaid_error_is_translated_to_plain_english():
    code, msg = pc.plaid_error(api_error("ITEM_LOGIN_REQUIRED"))
    assert code == "ITEM_LOGIN_REQUIRED" and "sign in again" in msg and "ufo.setup" in msg
    assert "RATE_LIMIT" in pc.plaid_error(api_error("RATE_LIMIT"))[1]
    assert pc.plaid_error(plaid.ApiException(status=500, reason="boom"))[0] == "UNKNOWN"


def test_a_broken_item_is_skipped_when_another_has_the_account(monkeypatch):
    class TwoItems(FakeClient):
        def accounts_balance_get(self, req):
            if req.access_token == "dead":
                raise api_error("ITEM_LOGIN_REQUIRED")
            return {"accounts": ACCOUNTS}

    monkeypatch.setattr(pc, "make_client", lambda s: TwoItems())
    b = pc.get_balances(S, [{"access_token": "dead"}, {"access_token": "ok"}], ["4821"])
    assert b == {"4821": ("Joint Checking …4821", 900.0)}


def test_only_broken_items_gives_a_clear_error_not_a_traceback(monkeypatch):
    class Dead(FakeClient):
        def accounts_balance_get(self, req):
            raise api_error("ITEM_LOGIN_REQUIRED")

    monkeypatch.setattr(pc, "make_client", lambda s: Dead())
    with pytest.raises(RuntimeError, match="sign in again"):
        pc.get_balances(S, [{"access_token": "dead"}], ["4821"])


def test_the_same_account_under_two_items_is_listed_once(monkeypatch):
    assert len(pc.list_accounts(S, [{"access_token": "a"}, {"access_token": "b"}])) == 3  # FakeClient returns the same 3 for each item
    assert len(pc.dedupe_accounts([{"name": "A", "mask": "1"}, {"name": "A", "mask": "1"}, {"name": "B", "mask": "2"}])) == 2


def test_get_balances_does_not_complain_about_duplicate_accounts_across_items(monkeypatch):
    b = pc.get_balances(S, [{"access_token": "a"}, {"access_token": "b"}], ["4821"])  # both items return the same account
    assert b["4821"][1] == 900.0


def test_prune_rules():
    ok = lambda bank: {"institution_id": bank, "error_code": None}  # noqa: E731
    bad = lambda bank: {"institution_id": bank, "error_code": "ITEM_LOGIN_REQUIRED"}  # noqa: E731
    # old broken + new healthy at the same bank: drop the old one
    assert pc.plan_prune([bad("chase"), ok("chase")]) == [0]
    # two healthy at the same bank: keep the newest
    assert pc.plan_prune([ok("chase"), ok("chase")]) == [0]
    # a broken item with no replacement is KEPT (the user must reconnect); other banks are untouched
    assert pc.plan_prune([bad("chase"), ok("fidelity")]) == []
    assert pc.plan_prune([ok("fidelity"), bad("chase"), ok("chase"), ok("fidelity")]) == [0, 1]
    # unknown bank: never removed
    assert pc.plan_prune([{"institution_id": None, "error_code": "X"}, ok("chase")]) == []


def test_prune_removes_the_dead_item_and_rewrites_the_token_file(monkeypatch, tmp_path):
    from ufo.providers.token_store import load_items, save_items

    path = tmp_path / "items.json"
    save_items([{"item_id": "old", "access_token": "dead"}, {"item_id": "new", "access_token": "ok"}], path)
    removed = []

    class C(FakeClient):
        def item_get(self, req):
            err = {"error_code": "ITEM_LOGIN_REQUIRED"} if req.access_token == "dead" else None
            return {"item": Model({"institution_id": "ins_chase", "error": err})}

        def item_remove(self, req):
            removed.append(req.access_token)

    monkeypatch.setattr(pc, "make_client", lambda s: C())
    lines = pc.prune_superseded_items(S, path)
    assert removed == ["dead"] and [i["item_id"] for i in load_items(path)] == ["new"] and "broken" in lines[0]


def test_prune_keeps_everything_when_nothing_is_superseded(monkeypatch, tmp_path):
    from ufo.providers.token_store import load_items, save_items

    path = tmp_path / "items.json"
    save_items([{"item_id": "a", "access_token": "ok"}], path)

    class C(FakeClient):
        def item_get(self, req):
            return {"item": Model({"institution_id": "ins_chase", "error": None})}

        def item_remove(self, req):
            raise AssertionError("must not remove anything")

    monkeypatch.setattr(pc, "make_client", lambda s: C())
    assert pc.prune_superseded_items(S, path) == [] and len(load_items(path)) == 1
