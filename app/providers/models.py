"""Shared provider envelopes; unknown facts stay null, never inferred."""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Generic, Literal, TypeVar

from pydantic import Field

from app.schemas import Schema


class ProviderError(Schema):
    code: str
    message: str
    retry_after: int | None = None


class Provenance(Schema):
    provider: str
    status: Literal["live", "cached", "unavailable"]
    fetched_at: datetime | None = None
    local_cache_hit: bool = False
    source_url: str
    notice: str


T = TypeVar("T")


class ProviderResult(Schema, Generic[T]):
    source: Provenance
    items: list[T] = Field(default_factory=list)
    error: ProviderError | None = None
    # Scope matters: local filtering/comparison does not imply exhaustive coverage.
    partial: bool = False
    pagination: dict[str, int | bool | None] = Field(default_factory=dict)


class Price(Schema):
    amount: Decimal = Field(ge=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")


class FlightOffer(Schema):
    id: str
    origin: str
    destination: str
    origin_airport: str | None = None
    destination_airport: str | None = None
    departure_at: datetime
    return_at: datetime | None = None
    airline: str | None = None
    flight_number: str | None = None
    stops: int | None = Field(default=None, ge=0)
    duration_min: int | None = Field(default=None, ge=0)
    price: Price
    booking_url: str | None = None
    seats_available: int | None = None
    baggage_kg: int | None = None
    cabin: str | None = None


class ProductOffer(Schema):
    id: str
    title: str
    price: Price | None = None
    image_url: str | None = None
    product_url: str | None = None
    category: str | None = None
    category_id: str | None = None
    brand: str | None = None
    color: str | None = None
    description: str | None = None
    condition: str | None = None
    availability_status: str | None = None
    in_stock: bool | None = None
    merchant: str | None = None
    price_as_of: datetime | None = None
    price_stale: bool | None = None


class MovieMetadata(Schema):
    id: str
    title: str
    synopsis: str = ""
    genre: list[str] = Field(default_factory=list)
    rating: float | None = Field(default=None, ge=0, le=10)
    language: str | None = None
    duration_min: int | None = Field(default=None, ge=0)
    release_date: str | None = None
    poster_url: str | None = None
    metadata_url: str
    confirmed_cinemaplus_screening: Literal[False] = False


def unavailable(provider, source_url, message, code="authorization_required", retry_after=None):
    return ProviderResult(source=Provenance(provider=provider, status="unavailable",
        source_url=source_url, notice=message),
        error=ProviderError(code=code, message=message, retry_after=retry_after))


def utcnow():
    return datetime.now(timezone.utc)
