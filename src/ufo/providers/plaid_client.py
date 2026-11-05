"""Read-only Plaid access: link an account (Hosted Link) and read live balances. Never moves money."""
from __future__ import annotations

import time

import plaid
from plaid.api import plaid_api
from plaid.model.accounts_balance_get_request import AccountsBalanceGetRequest
from plaid.model.country_code import CountryCode
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.link_token_create_hosted_link import LinkTokenCreateHostedLink
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.link_token_get_request import LinkTokenGetRequest
from plaid.model.products import Products

from ..config import Settings
from .token_store import save_item

_HOSTS = {"sandbox": plaid.Environment.Sandbox, "production": plaid.Environment.Production}


def make_client(s: Settings) -> plaid_api.PlaidApi:
    if not (s.plaid_client_id and s.plaid_secret):
        raise ValueError("Set PLAID_CLIENT_ID and PLAID_SECRET in .env (see .env.example)")
    cfg = plaid.Configuration(host=_HOSTS[s.plaid_env], api_key={"clientId": s.plaid_client_id, "secret": s.plaid_secret})
    return plaid_api.PlaidApi(plaid.ApiClient(cfg))


def link_account(s: Settings, timeout_s: int = 900) -> None:
    """One-time: open the printed URL, connect your bank; the access token is stored in .data/items.json."""
    client = make_client(s)
    link = client.link_token_create(LinkTokenCreateRequest(
        client_name="UFO", language="en", country_codes=[CountryCode("US")],
        user=LinkTokenCreateRequestUser(client_user_id="me"), products=[Products("transactions")],
        hosted_link=LinkTokenCreateHostedLink(),
    ))
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


def _val(x):
    """Plaid enum models expose .value; plain strings pass through."""
    return getattr(x, "value", x) or ""


def pick_checking_balance(accounts: list[dict], mask: str | None = None) -> tuple[str, float]:
    """Choose the checking account (by mask if given) and return (label, available balance).
    Falls back to the current balance when Plaid has no available figure. Pure so it can be tested."""
    checking = [a for a in accounts if _val(a.get("subtype")) == "checking" and (not mask or a.get("mask") == mask)]
    if not checking:
        raise ValueError(f"No checking account found{f' with mask {mask}' if mask else ''}.")
    if len(checking) > 1:
        raise ValueError("Several checking accounts found; set account_mask in the alert config: " + ", ".join(f"{a['name']} …{a['mask']}" for a in checking))
    a = checking[0]
    bal = a["balances"]["available"]
    if bal is None:
        bal = a["balances"]["current"]
    return f"{a['name']} …{a['mask']}", float(bal)


def get_checking_balance(s: Settings, items: list[dict], mask: str | None = None) -> tuple[str, float]:
    client = make_client(s)
    for item in items:
        resp = client.accounts_balance_get(AccountsBalanceGetRequest(access_token=item["access_token"]))
        accounts = [a.to_dict() for a in resp["accounts"]]
        try:
            return pick_checking_balance(accounts, mask)
        except ValueError as e:
            if "No checking" not in str(e):
                raise
    raise ValueError("No linked item has a matching checking account. Run scripts/link_account.py first.")
