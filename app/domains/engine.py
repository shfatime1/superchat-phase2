from app.domain_models import DomainResult
from app.domains.cinema import CinemaService
from app.domains.common import DomainIssue, SeatInventory
from app.domains.flights import FlightsService
from app.domains.shopping import ShoppingService
from app.repositories import DataSourceError
from app.schemas import RoutingResult
from app.state import apply_routing
from time import perf_counter, monotonic
from app.diagnostics import current


class DomainEngine:
    def __init__(self, repositories):
        self.inventory = SeatInventory()
        self.services = {
            "flights": FlightsService(repositories.flights, self.inventory),
            "shopping": ShoppingService(repositories.products),
            "cinema": CinemaService(repositories.movies, repositories.cinemas,
                                    repositories.showtimes, self.inventory),
        }

    def execute(self, routing, state, on_result=None):
        outcomes = []
        for index, intent in enumerate(routing.intents):
            trace = current.get()
            started = perf_counter()
            if trace:
                trace.progress("provider", domain=intent.domain)
                # A slow provider receives a share of the remaining time rather
                # than exhausting the entire mixed request before other domains.
                trace.provider_budget = max(0.01, (trace.deadline - monotonic() - 5) / (len(routing.intents) - index))
            # Merge and execute in order, including multiple intents in one domain.
            apply_routing(state, RoutingResult(category=intent.domain, domains=[intent.domain], intents=[intent]))
            snapshot = getattr(state, intent.domain).model_copy(deep=True)
            try:
                date_pairs = (("departure_date_text", "departure_date"), ("return_date_text", "return_date")) \
                    if intent.domain == "flights" else (("date_text", "date"),) if intent.domain == "cinema" else ()
                if any(getattr(snapshot.parameters, text) and getattr(snapshot.parameters, date) is None
                       for text, date in date_pairs):
                    raise DomainIssue("date")
                outcome = self.services[intent.domain].execute(intent, state)
            except DomainIssue as exc:
                outcome = DomainResult(domain=intent.domain, operation=intent.intent, status=exc.status,
                                       code=exc.code, missing=exc.missing, data=exc.data)
            except DataSourceError:
                setattr(state, intent.domain, snapshot)
                outcome = DomainResult(domain=intent.domain, operation=intent.intent,
                                       status="error", code="data_unavailable")
            outcomes.append(outcome)
            if trace:
                trace.check()
                trace.data["stages"].append({"stage": intent.domain, "duration_ms": round((perf_counter() - started) * 1000)})
                if outcome.status == "error":
                    trace.data["errors"].append({"domain": intent.domain, "code": outcome.code})
            if on_result:
                on_result(outcome)
        # Shared metadata is applied without merging intents a second time.
        apply_routing(state, RoutingResult(category="ambiguous", language=routing.language,
                                           preferences=routing.preferences))
        if routing.domains:
            state.last_active_domain = routing.domains[0] if len(routing.domains) == 1 else None
        return outcomes
