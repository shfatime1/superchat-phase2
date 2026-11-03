"""Process-local sessions with independent, atomic per-session updates."""

from contextlib import contextmanager
from threading import RLock
from typing import Iterator, Literal
from uuid import UUID, uuid4

from pydantic import Field, JsonValue

from app.domain_models import DomainResult, PendingOperation, Reservation

from app.schemas import (CinemaParameters, Domain, FlightParameters, RoutingResult,
                         Schema, ShoppingParameters)


class DomainContext(Schema):
    provider_snapshot: dict[str, JsonValue] = Field(default_factory=dict)
    last_result_ids: list[str] = Field(default_factory=list)
    selected_ids: list[str] = Field(default_factory=list)
    pending: PendingOperation | None = None


class FlightsState(DomainContext):
    intent: str | None = None
    parameters: FlightParameters = Field(default_factory=FlightParameters)
    reservations: list[Reservation] = Field(default_factory=list)


class ShoppingState(DomainContext):
    intent: str | None = None
    parameters: ShoppingParameters = Field(default_factory=ShoppingParameters)
    cart: dict[str, int] = Field(default_factory=dict)


class CinemaState(DomainContext):
    intent: str | None = None
    parameters: CinemaParameters = Field(default_factory=CinemaParameters)
    last_showtime_ids: list[str] = Field(default_factory=list)
    selected_showtime_ids: list[str] = Field(default_factory=list)
    reservations: list[Reservation] = Field(default_factory=list)


class HistoryTurn(Schema):
    role: Literal["user", "assistant"]
    content: str
    routing: RoutingResult | None = None
    results: list[DomainResult] = Field(default_factory=list)
    debug: dict[str, JsonValue] | None = None


class SessionState(Schema):
    session_id: UUID = Field(default_factory=uuid4)
    flights: FlightsState = Field(default_factory=FlightsState)
    shopping: ShoppingState = Field(default_factory=ShoppingState)
    cinema: CinemaState = Field(default_factory=CinemaState)
    history: list[HistoryTurn] = Field(default_factory=list)
    last_active_domain: Domain | None = None
    language: str | None = None
    preferences: list[str] = Field(default_factory=list)


class SessionNotFound(LookupError):
    pass


class SessionStore:
    def __init__(self):
        self._sessions: dict[UUID, SessionState] = {}
        self._locks: dict[UUID, RLock] = {}
        self._guard = RLock()

    def _lock_for(self, session_id: UUID) -> RLock:
        with self._guard:
            if session_id not in self._sessions:
                raise SessionNotFound("Session not found")
            return self._locks[session_id]

    def get(self, session_id: UUID) -> SessionState:
        with self._lock_for(session_id):
            return self._sessions[session_id].model_copy(deep=True)

    @contextmanager
    def transaction(self, session_id: UUID | None) -> Iterator[SessionState]:
        if session_id is None:
            state = SessionState()
            yield state
            # New sessions become visible only after a successful turn.
            with self._guard:
                self._locks[state.session_id] = RLock()
                self._sessions[state.session_id] = state.model_copy(deep=True)
        else:
            with self._lock_for(session_id):
                state = self._sessions[session_id].model_copy(deep=True)
                yield state
                self._sessions[session_id] = state.model_copy(deep=True)


def apply_routing(state: SessionState, result: RoutingResult) -> None:
    for extracted in result.intents:
        domain_state = getattr(state, extracted.domain)
        new_shopping_query = (extracted.domain == "shopping" and extracted.intent == "search" and
                              extracted.parameters.query is not None and domain_state.parameters.query is not None and
                              extracted.parameters.query.casefold() != domain_state.parameters.query.casefold())
        reset = extracted.reset_context or new_shopping_query
        if reset:
            domain_state.provider_snapshot = {}
            domain_state.last_result_ids = []
            domain_state.selected_ids = []
            domain_state.pending = None
            if extracted.domain == "cinema":
                domain_state.last_showtime_ids = []
                domain_state.selected_showtime_ids = []
        previous = {} if reset else domain_state.parameters.model_dump()
        if extracted.domain == "shopping" and extracted.parameters.offset is None and extracted.intent in {"search", "filter", "sort", "follow_up"}:
            if any(value is not None and previous.get(key) != value for key, value in extracted.parameters.model_dump().items()
                   if key in {"query", "category", "brand", "color", "currency", "min_price", "max_price", "min_price_azn", "max_price_azn", "sort_by"}):
                previous.pop("offset", None)
        if extracted.domain == "shopping" and extracted.parameters.currency:
            old_currency = previous.get("currency") or ("AZN" if any(previous.get(k) is not None for k in ("min_price_azn", "max_price_azn")) else None)
            if old_currency and old_currency.upper() != extracted.parameters.currency.upper():
                for key in ("min_price", "max_price", "min_price_azn", "max_price_azn"):
                    previous.pop(key, None)
        for key in extracted.clear_parameters:
            previous.pop(key, None)
        previous.update(extracted.parameters.model_dump(exclude_none=True))
        domain_state.parameters = type(domain_state.parameters).model_validate(previous)
        domain_state.intent = extracted.intent
    if result.domains:
        # A mixed request has no single implicit referent for the next short reply.
        state.last_active_domain = result.domains[0] if len(result.domains) == 1 else None
    if result.language:
        state.language = result.language
    for preference in result.preferences:
        if preference not in state.preferences:
            state.preferences.append(preference)
