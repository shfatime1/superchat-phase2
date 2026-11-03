"""Validated routing and API contracts. Parameters have no assumed defaults."""

from datetime import date as Date
from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Schema(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")


class Domain(str, Enum):
    FLIGHTS = "flights"
    SHOPPING = "shopping"
    CINEMA = "cinema"


class Category(str, Enum):
    FLIGHTS = "flights"
    SHOPPING = "shopping"
    CINEMA = "cinema"
    MIXED = "mixed"
    FOLLOW_UP = "follow_up"
    AMBIGUOUS = "ambiguous"
    OUT_OF_SCOPE = "out_of_scope"


class FlightParameters(Schema):
    currency: str | None = Field(default=None, pattern=r"^[A-Za-z]{3}$")
    flight_number: str | None = None
    origin: str | None = None
    destination: str | None = None
    departure_date: Date | None = None
    departure_date_text: str | None = None
    return_date: Date | None = None
    return_date_text: str | None = None
    passengers: int | None = Field(default=None, ge=1)
    min_price_azn: float | None = Field(default=None, ge=0)
    max_price_azn: float | None = Field(default=None, ge=0)
    stops: int | None = Field(default=None, ge=0)
    airline: str | None = None
    cabin: str | None = None
    departure_time: str | None = None
    departure_time_from: str | None = None
    departure_time_to: str | None = None
    baggage_kg: int | None = Field(default=None, ge=0)
    sort_by: str | None = None
    flight_ids: list[str] | None = None
    reference: str | None = None
    result_positions: list[int] | None = None


class ShoppingParameters(Schema):
    currency: str | None = Field(default=None, pattern=r"^[A-Za-z]{3}$")
    min_price: float | None = Field(default=None, ge=0)
    max_price: float | None = Field(default=None, ge=0)
    query: str | None = None
    category: str | None = None
    brand: str | None = None
    min_price_azn: float | None = Field(default=None, ge=0)
    max_price_azn: float | None = Field(default=None, ge=0)
    color: str | None = None
    quantity: int | None = Field(default=None, ge=1)
    in_stock: bool | None = None
    sort_by: str | None = None
    product_ids: list[str] | None = None
    reference: str | None = None
    result_positions: list[int] | None = None


class CinemaParameters(Schema):
    movie_title: str | None = None
    genre: str | None = None
    language: str | None = None
    min_rating: float | None = Field(default=None, ge=0, le=10)
    cinema_name: str | None = None
    district: str | None = None
    date: Date | None = None
    date_text: str | None = None
    time: str | None = None
    tickets: int | None = Field(default=None, ge=1)
    max_price_azn: float | None = Field(default=None, ge=0)
    movie_ids: list[str] | None = None
    cinema_ids: list[str] | None = None
    showtime_ids: list[str] | None = None
    reference: str | None = None
    result_positions: list[int] | None = None
    sort_by: str | None = None


class IntentBase(Schema):
    intent: Literal["search", "filter", "sort", "details", "compare", "availability",
                    "reserve", "cart_add", "cart_remove", "cart_view", "resume", "follow_up"]
    reset_context: bool = False
    clear_parameters: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_clears(self):
        if any(key not in type(self.parameters).model_fields for key in self.clear_parameters):
            raise ValueError("Unknown parameter to clear")
        return self


class FlightIntent(IntentBase):
    domain: Literal["flights"]
    parameters: FlightParameters = Field(default_factory=FlightParameters)


class ShoppingIntent(IntentBase):
    domain: Literal["shopping"]
    parameters: ShoppingParameters = Field(default_factory=ShoppingParameters)


class CinemaIntent(IntentBase):
    domain: Literal["cinema"]
    parameters: CinemaParameters = Field(default_factory=CinemaParameters)


class RoutingResult(Schema):
    source: Literal["gemini", "local"] = "gemini"
    category: Category
    domains: list[Domain] = Field(default_factory=list)
    intents: list[FlightIntent | ShoppingIntent | CinemaIntent] = Field(default_factory=list)
    clarification: str | None = None
    language: str | None = None
    preferences: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def coherent_route(self):
        if len(self.domains) != len(set(self.domains)):
            raise ValueError("Duplicate domains")
        intent_domains = {Domain(intent.domain) for intent in self.intents}
        if intent_domains != set(self.domains):
            raise ValueError("Domains must match the extracted intents")
        if self.category.value in {domain.value for domain in Domain}:
            if self.domains != [Domain(self.category.value)]:
                raise ValueError("A domain category must have exactly that domain")
        if self.category == Category.MIXED and len(self.domains) < 2:
            raise ValueError("Mixed requires at least two domains")
        if self.category in {Category.AMBIGUOUS, Category.OUT_OF_SCOPE} and self.intents:
            raise ValueError("Unresolved or out-of-scope requests cannot update domains")
        return self


class ChatRequest(Schema):
    message: str = Field(min_length=1, max_length=8000)
    session_id: UUID | None = None
    request_id: UUID | None = None

    @field_validator("message")
    @classmethod
    def meaningful_message(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Message must not be blank")
        return value
