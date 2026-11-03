"""Domain outcomes and session-owned mock operations."""

from typing import Literal
from uuid import uuid4

from pydantic import Field, JsonValue

from app.schemas import Schema


class Reservation(Schema):
    confirmation_id: str = Field(default_factory=lambda: "MOCK-" + uuid4().hex.upper())
    record_id: str
    quantity: int
    unit_price_azn: str
    total_azn: str
    mock: Literal[True] = True
    paid: Literal[False] = False


class PendingOperation(Schema):
    action: str
    ids: list[str] = Field(default_factory=list)
    quantity: int | None = None


class DomainResult(Schema):
    domain: str
    operation: str
    status: Literal["ok", "no_results", "clarification", "error"] = "ok"
    code: str = "results"
    data: dict[str, JsonValue] = Field(default_factory=dict)
    missing: list[str] = Field(default_factory=list)
