"""Shared schemas. Mirrors the normalized holding shape used by the Node prototype (fin-advisor)."""
from datetime import date
from pydantic import BaseModel


class Holding(BaseModel):
    account: str
    account_mask: str
    symbol: str
    quantity: float
    price: float
    value: float
    is_cash: bool = False
    cost_basis: float | None = None


class Bill(BaseModel):
    name: str
    amount: float
    due: date
