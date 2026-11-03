"""Environment-first settings with optional local dotenv convenience."""

import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REFERENCE_DATE = date(2026, 11, 2)


@dataclass(frozen=True)
class Settings:
    data_mode: str = "providers"
    travelpayouts_token: str | None = field(default=None, repr=False)
    tmdb_token: str | None = field(default=None, repr=False)
    cinema_provider: str = "auto"
    ebay_token: str | None = field(default=None, repr=False)
    ebay_client_id: str | None = field(default=None, repr=False)
    ebay_client_secret: str | None = field(default=None, repr=False)
    shopping_provider: str = "auto"
    buywhere_token: str | None = field(default=None, repr=False)
    buywhere_market: str = "US"
    ebay_marketplace: str = "EBAY_US"
    flight_currency: str = "AZN"
    flight_market: str | None = None
    provider_timeout_seconds: float = 8.0
    provider_retries: int = 2
    provider_cache_ttl: int = 300
    api_key: str | None = field(default=None, repr=False)
    model: str = "gemini-flash-latest"
    data_dir: Path = PROJECT_ROOT / "data"
    routing_mode: str = "auto"
    gemini_timeout_ms: int = 30000
    response_timeout_ms: int = 4000
    secure_cookies: bool = False

    def reference_date(self):
        return REFERENCE_DATE if self.data_mode == "fixtures" else datetime.now(timezone(timedelta(hours=4))).date()

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv(PROJECT_ROOT / ".env", override=False)
        return cls(
            data_mode=os.getenv("SUPERCHAT_DATA_MODE", "providers").strip().lower(),
            travelpayouts_token=(os.getenv("TRAVELPAYOUTS_API_TOKEN") or "").strip() or None,
            tmdb_token=(os.getenv("TMDB_READ_ACCESS_TOKEN") or "").strip() or None,
            cinema_provider=os.getenv("CINEMA_PROVIDER", "auto").strip().lower(),
            ebay_token=(os.getenv("EBAY_ACCESS_TOKEN") or "").strip() or None,
            ebay_client_id=(os.getenv("EBAY_CLIENT_ID") or "").strip() or None,
            ebay_client_secret=(os.getenv("EBAY_CLIENT_SECRET") or "").strip() or None,
            shopping_provider=os.getenv("SHOPPING_PROVIDER", "auto").strip().lower(),
            buywhere_token=(os.getenv("BUYWHERE_API_KEY") or "").strip() or None,
            buywhere_market=os.getenv("BUYWHERE_MARKET", "US").strip().upper(),
            ebay_marketplace=os.getenv("EBAY_MARKETPLACE", "EBAY_US").strip(),
            flight_currency=os.getenv("FLIGHT_CURRENCY", "AZN").strip().upper(),
            flight_market=(os.getenv("FLIGHT_MARKET") or "").strip() or None,
            provider_timeout_seconds=max(0.1, min(30, float(os.getenv("PROVIDER_TIMEOUT_SECONDS", "8")))),
            provider_retries=max(0, min(3, int(os.getenv("PROVIDER_RETRIES", "2")))),
            provider_cache_ttl=max(1, min(86400, int(os.getenv("PROVIDER_CACHE_TTL", "300")))),
            api_key=(os.getenv("GEMINI_API_KEY") or "").strip() or None,
            model=(os.getenv("GEMINI_MODEL") or "").strip() or "gemini-flash-latest",
            routing_mode=(os.getenv("SUPERCHAT_ROUTING_MODE") or "auto").strip().lower() or "auto",
            gemini_timeout_ms=int(os.getenv("GEMINI_TIMEOUT_MS", "30000")),
            response_timeout_ms=int(os.getenv("GEMINI_RESPONSE_TIMEOUT_MS", "4000")),
            secure_cookies=os.getenv("COOKIE_SECURE", "false").lower() == "true",
        )
