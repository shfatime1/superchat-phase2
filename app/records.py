"""Models matching the five official JSON schemas (including native names)."""

from datetime import date, datetime, time

from pydantic import BaseModel, ConfigDict


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str


class Airport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    city: str


class Flight(Record):
    airline: str
    flight_number: str
    origin: Airport
    destination: Airport
    departure_local: datetime
    arrival_local: datetime
    duration_min: int
    stops: int
    via: str | None
    price_azn: float
    cabin: str
    baggage_kg: int
    seats_available: int


class LocalizedName(BaseModel):
    model_config = ConfigDict(extra="forbid")
    en: str
    az: str
    ru: str


class Product(Record):
    name: LocalizedName
    category: str
    brand: str
    price_azn: float
    rating: float
    stock: int
    color: str
    description: str


class Movie(Record):
    title: str
    genre: list[str]
    language: str
    duration_min: int
    age_rating: str
    rating: float
    synopsis: str


class Cinema(Record):
    name: str
    district: str
    address: str


class Showtime(Record):
    movie_id: str
    cinema_id: str
    date: date
    time: time
    hall: str
    price_azn: float
    seats_total: int
    seats_available: int
