"""Settings loaded from environment variables (never from the repo)."""
import os
from pathlib import Path
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
    telegram_bot_token: str | None = None
    telegram_chat_ids: list[str] = []  # one per person who should get alerts
    cushion_usd: float = 1000.0


def _load_dotenv(path: str = ".env") -> None:
    """Minimal .env reader (KEY=VALUE lines); real environment variables win."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.split(" #")[0].strip().strip("\"'"))


def load_settings() -> Settings:
    _load_dotenv()
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
        telegram_bot_token=e.get("TELEGRAM_BOT_TOKEN"),
        telegram_chat_ids=[c.strip() for c in e.get("TELEGRAM_CHAT_IDS", "").split(",") if c.strip()],
        cushion_usd=float(e.get("CUSHION_USD", "1000")),
    )
