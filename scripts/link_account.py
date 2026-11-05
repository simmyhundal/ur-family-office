"""One-time: link your checking account through Plaid Hosted Link (read-only)."""
from ufo.config import load_settings
from ufo.providers.plaid_client import link_account

if __name__ == "__main__":
    link_account(load_settings())
