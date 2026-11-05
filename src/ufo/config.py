"""Settings loaded from environment variables (never from the repo)."""
import os
from pydantic import BaseModel


class Settings(BaseModel):
    environment: str = "development"
    plaid_client_id: str | None = None
    plaid_secret: str | None = None
    plaid_env: str = "sandbox"
    twilio_account_sid: str | None = None
    twilio_auth_token: str | None = None
    twilio_from_number: str | None = None
    alert_phone_number: str | None = None
    cushion_usd: float = 1000.0


def load_settings() -> Settings:
    e = os.environ
    return Settings(
        environment=e.get("ENVIRONMENT", "development"),
        plaid_client_id=e.get("PLAID_CLIENT_ID"),
        plaid_secret=e.get("PLAID_SECRET"),
        plaid_env=e.get("PLAID_ENV", "sandbox"),
        twilio_account_sid=e.get("TWILIO_ACCOUNT_SID"),
        twilio_auth_token=e.get("TWILIO_AUTH_TOKEN"),
        twilio_from_number=e.get("TWILIO_FROM_NUMBER"),
        alert_phone_number=e.get("ALERT_PHONE_NUMBER"),
        cushion_usd=float(e.get("CUSHION_USD", "1000")),
    )
