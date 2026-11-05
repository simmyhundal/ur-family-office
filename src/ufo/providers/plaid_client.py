"""Read-only Plaid access: link an account (Hosted Link) and read live balances. Never moves money."""
from __future__ import annotations

import time

import plaid
from plaid.api import plaid_api
from plaid.model.accounts_balance_get_request import AccountsBalanceGetRequest
from plaid.model.accounts_get_request import AccountsGetRequest
from plaid.model.country_code import CountryCode
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.liabilities_get_request import LiabilitiesGetRequest
from plaid.model.liabilities_get_request_options import LiabilitiesGetRequestOptions
from plaid.model.link_token_create_hosted_link import LinkTokenCreateHostedLink
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.link_token_transactions import LinkTokenTransactions
from plaid.model.link_token_get_request import LinkTokenGetRequest
from plaid.model.products import Products
from plaid.model.transactions_recurring_get_request import TransactionsRecurringGetRequest

from ..config import Settings
from .token_store import save_item

HISTORY_DAYS = 730  # Plaid's maximum
_HOSTS = {"sandbox": plaid.Environment.Sandbox, "production": plaid.Environment.Production}


def make_client(s: Settings) -> plaid_api.PlaidApi:
    if not (s.plaid_client_id and s.plaid_secret):
        raise ValueError("Set PLAID_CLIENT_ID and PLAID_SECRET in .env (see .env.example)")
    cfg = plaid.Configuration(host=_HOSTS[s.plaid_env], api_key={"clientId": s.plaid_client_id, "secret": s.plaid_secret})
    return plaid_api.PlaidApi(plaid.ApiClient(cfg))


def build_link_request() -> LinkTokenCreateRequest:
    return LinkTokenCreateRequest(
        client_name="UFO", language="en", country_codes=[CountryCode("US")],
        user=LinkTokenCreateRequestUser(client_user_id="me"), products=[Products("transactions")],
        optional_products=[Products("liabilities")],  # credit-card statement balances and due dates
        hosted_link=LinkTokenCreateHostedLink(),
        # History is chosen once, when the Item is created (default 90 days; cannot be raised later without re-linking).
        # Recurring-bill detection works best with 180+ days, so ask for the maximum.
        transactions=LinkTokenTransactions(days_requested=HISTORY_DAYS),
    )


def link_account(s: Settings, timeout_s: int = 900) -> None:
    """One-time: open the printed URL, connect your bank; the access token is stored in .data/items.json."""
    client = make_client(s)
    link = client.link_token_create(build_link_request())
    print(f"Open this URL in your browser and connect your account:\n\n  {link['hosted_link_url']}\n\nWaiting (Ctrl-C to cancel)...")
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        time.sleep(4)
        got = client.link_token_get(LinkTokenGetRequest(link_token=link["link_token"]))
        added = [r for sess in (got.get("link_sessions") or []) for r in ((sess.get("results") or {}).get("item_add_results") or [])]
        for r in added:
            ex = client.item_public_token_exchange(ItemPublicTokenExchangeRequest(public_token=r["public_token"]))
            save_item({"item_id": ex["item_id"], "access_token": ex["access_token"]})
            print(f"Linked item {ex['item_id']}. Token saved to .data/items.json")
        if added:
            return
    raise TimeoutError("Timed out waiting for the link to complete.")


def pick_account_balance(accounts: list[dict], mask: str) -> tuple[str, float]:
    """Find the account with this mask and return (label, available balance), falling back to current.
    Pure so it can be tested."""
    found = [a for a in accounts if a.get("mask") == mask]
    if not found:
        raise ValueError(f"No linked account with mask {mask}. Run scripts/link_account.py, or check the mask in the alert config.")
    if len(found) > 1:
        raise ValueError(f"Several accounts end in {mask}; use a longer mask.")
    a = found[0]
    bal = a["balances"]["available"]
    if bal is None:
        bal = a["balances"]["current"]
    return f"{a['name']} …{a['mask']}", float(bal)


def get_balances(s: Settings, items: list[dict], masks: list[str]) -> dict[str, tuple[str, float]]:
    """Live balances for the given account masks across all linked items: {mask: (label, available)}."""
    client = make_client(s)
    accounts: list[dict] = []
    for item in items:
        resp = client.accounts_balance_get(AccountsBalanceGetRequest(access_token=item["access_token"]))
        accounts += [a.to_dict() for a in resp["accounts"]]
    return {m: pick_account_balance(accounts, m) for m in masks}


def get_recurring_outflows(s: Settings, items: list[dict], mask: str) -> list[dict]:
    """Plaid's detected recurring outflow streams for the account with this mask (read-only).
    Raises RuntimeError with a plain message when detection is unavailable, so the caller can fall back to manual bills."""
    client = make_client(s)
    for item in items:
        accounts = [a.to_dict() for a in client.accounts_get(AccountsGetRequest(access_token=item["access_token"]))["accounts"]]
        found = [a for a in accounts if a.get("mask") == mask]
        if not found:
            continue
        try:
            resp = client.transactions_recurring_get(TransactionsRecurringGetRequest(
                access_token=item["access_token"], account_ids=[found[0]["account_id"]]))
        except plaid.ApiException as e:
            raise RuntimeError(f"Plaid could not return recurring transactions ({getattr(e, 'reason', e)}). "
                               "The item may not have the transactions product yet or history is still loading.") from e
        return [st.to_dict() for st in resp["outflow_streams"]]
    raise RuntimeError(f"No linked account with mask {mask}.")


def get_credit_card_liabilities(s: Settings, items: list[dict], masks: list[str]) -> list[dict]:
    """Statement balance, minimum payment and due date for the credit cards with these masks (read-only)."""
    client = make_client(s)
    out: list[dict] = []
    for item in items:
        accounts = [a.to_dict() for a in client.accounts_get(AccountsGetRequest(access_token=item["access_token"]))["accounts"]]
        ids = {a["account_id"]: a for a in accounts if a.get("mask") in masks}
        if not ids:
            continue
        try:
            resp = client.liabilities_get(LiabilitiesGetRequest(
                access_token=item["access_token"], options=LiabilitiesGetRequestOptions(account_ids=list(ids))))
        except plaid.ApiException as e:
            raise RuntimeError(f"Plaid could not return credit-card liabilities ({getattr(e, 'reason', e)}). "
                               "Re-link with the liabilities product, or check that the card is included in the link.") from e
        for c in (resp["liabilities"].to_dict().get("credit") or []):
            a = ids.get(c["account_id"])
            if a:
                out.append({"name": a["name"], "mask": a["mask"], **{k: c.get(k) for k in (
                    "next_payment_due_date", "minimum_payment_amount", "last_statement_balance", "is_overdue")}})
    missing = set(masks) - {c["mask"] for c in out}
    if missing:
        raise RuntimeError("No credit card found for mask(s): " + ", ".join(sorted(missing)) + ". Link the card, or fix credit_card_masks.")
    return out


def list_accounts(s: Settings, items: list[dict]) -> list[dict]:
    """Linked accounts (name, mask, type, subtype) without balances, for the setup wizard's pickers."""
    client = make_client(s)
    out: list[dict] = []
    for item in items:
        for a in client.accounts_get(AccountsGetRequest(access_token=item["access_token"]))["accounts"]:
            d = a.to_dict()
            out.append({"name": d["name"], "mask": d.get("mask"), "type": _val(d.get("type")), "subtype": _val(d.get("subtype"))})
    return out
