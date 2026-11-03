"""Coordinate routing, deterministic domain operations and grounded responses."""

from datetime import date
from uuid import UUID

from pydantic import Field
from time import perf_counter

from app.config import REFERENCE_DATE
from app.domain_models import DomainResult
from app.routing import Router
from app.schemas import RoutingResult, Schema
from app.state import HistoryTurn, SessionState, SessionStore
from app.languages import detect_language, requested_language, language_only
from app.provider_locale import localize_outcomes
from app.diagnostics import Trace
from app.responses import render
from app.query_context import explicit_domains


class ChatResponse(Schema):
    session_id: UUID
    reference_date: date = REFERENCE_DATE
    routing: RoutingResult
    state: SessionState
    message: str
    results: list[DomainResult] = Field(default_factory=list)
    debug: dict | None = None


class ChatService:
    def __init__(self, router: Router, sessions: SessionStore, formulator):
        self.router = router
        self.sessions = sessions
        self.formulator = formulator
        self.engine = None  # Assigned after repository startup validation.

    def chat(self, message: str, session_id: UUID | None = None, language: str | None = None,
             emit=None, refresh_cache=False, domain_hint=None) -> ChatResponse:
        trace = Trace(emit, self.formulator.settings.chat_timeout_seconds, refresh_cache)
        with trace.activate():
            return self._chat(message, session_id, language, trace, domain_hint)

    def _chat(self, message, session_id, language, trace, domain_hint=None):
        with self.sessions.transaction(session_id) as state:
            trace.scope = str(state.session_id)
            trace.progress("routing")
            started = perf_counter()
            switch = requested_language(message)
            only_language = language_only(message)
            if only_language:
                routing = RoutingResult(category="ambiguous", source="local", language=switch)
            else:
                routing_state = state
                hint = domain_hint if not explicit_domains(message) else None
                if hint:
                    # A deliberate sidebar choice supplies context for vague text;
                    # an explicit domain in the message always wins.
                    routing_state = state.model_copy(deep=False)
                    routing_state.last_active_domain = hint
                routing = self.router.route(message, routing_state)
                if hint and routing.domains != [hint] and hasattr(self.router, "local"):
                    routing = self.router.local.route(message, routing_state)
                    routing.fallback_reason = "selected_domain_mismatch"
                # Route EVERY new turn. Only provider data is cached for 30 minutes.
            routing.language = switch or language or detect_language(message, routing.language or state.language)
            trace.data["routing"] = {"source": routing.source, "category": routing.category.value,
                "domains": [d.value for d in routing.domains], "cache": "miss",
                "fallback_reason": routing.fallback_reason,
                "domain_hint": domain_hint,
                "duration_ms": round((perf_counter() - started) * 1000), "intents": [
                    {"domain": i.domain, "operation": i.intent, "reset_context": i.reset_context,
                     "fields": list(i.parameters.model_dump(exclude_none=True))} for i in routing.intents]}
            trace.check()
            with self.engine.inventory.transaction():
                def available(outcome):
                    localize_outcomes([outcome], routing.language)
                    text = render(outcome, routing.language) + "\n\n"
                    # Grounded sections are available as each domain finishes; no
                    # model reasoning or unvalidated tokens are streamed.
                    for line in text.splitlines(keepends=True):
                        trace.emit("text", {"delta": line})
                results = self.engine.execute(routing, state, on_result=available)
                trace.progress("response")
                started = perf_counter()
                options = {"use_gemini": False} if routing.source == "local" else {}
                reply = self.formulator.formulate(message, routing.language or state.language, results,
                                                  routing.category.value, routing.clarification, **options)
                if only_language:
                    reply = {"az": "Azərbaycan dilində davam edək.", "en": "Let’s continue in English.", "ru": "Продолжим на русском."}[switch]
                if not results:
                    trace.emit("text", {"delta": reply})
                trace.check()
                trace.data["stages"].append({"stage": "response", "duration_ms": round((perf_counter() - started) * 1000)})
                debug = trace.finish()
                state.history.extend([
                    HistoryTurn(role="user", content=message),
                    HistoryTurn(role="assistant", content=reply, routing=routing.model_copy(deep=True), results=results, debug=debug),
                ])
                return ChatResponse(session_id=state.session_id, routing=routing, results=results,
                                    state=state.model_copy(deep=True), message=reply, debug=debug,
                                    reference_date=self.formulator.settings.reference_date())
