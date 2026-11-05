from ufo.config import load_settings
from ufo.models import Holding


def test_settings_defaults(monkeypatch):
    monkeypatch.delenv("CUSHION_USD", raising=False)
    assert load_settings().cushion_usd == 1000.0


def test_holding_model():
    h = Holding(account="Brokerage", account_mask="7693", symbol="IVV", quantity=1, price=770.0, value=770.0)
    assert not h.is_cash
