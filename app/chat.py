"""Coordinate routing, deterministic domain operations and grounded responses."""

from datetime import date
from uuid import UUID

from pydantic import Field

from app.config import REFERENCE_DATE
from app.domain_models import DomainResult
from app.routing import Router
from app.schemas import RoutingResult, Schema
from app.state import HistoryTurn, SessionState, SessionStore


class ChatResponse(Schema):
    session_id: UUID
    reference_date: date = REFERENCE_DATE
    routing: RoutingResult
    state: SessionState
    message: str
    results: list[DomainResult] = Field(default_factory=list)


class ChatService:
    def __init__(self, router: Router, sessions: SessionStore, formulator):
        self.router = router
        self.sessions = sessions
        self.formulator = formulator
        self.engine = None  # Assigned after repository startup validation.

    def chat(self, message: str, session_id: UUID | None = None) -> ChatResponse:
        with self.sessions.transaction(session_id) as state:
            routing = self.router.route(message, state)
            with self.engine.inventory.transaction():
                results = self.engine.execute(routing, state)
                options = {"use_gemini": False} if routing.source == "local" else {}
                reply = self.formulator.formulate(message, routing.language or state.language, results,
                                                  routing.category.value, routing.clarification, **options)
                state.history.extend([
                    HistoryTurn(role="user", content=message),
                    HistoryTurn(role="assistant", content=reply, routing=routing.model_copy(deep=True), results=results),
                ])
                return ChatResponse(session_id=state.session_id, routing=routing, results=results,
                                    state=state.model_copy(deep=True), message=reply,
                                    reference_date=self.formulator.settings.reference_date())
