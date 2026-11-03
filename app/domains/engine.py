from app.domain_models import DomainResult
from app.domains.cinema import CinemaService
from app.domains.common import DomainIssue, SeatInventory
from app.domains.flights import FlightsService
from app.domains.shopping import ShoppingService
from app.repositories import DataSourceError
from app.schemas import RoutingResult
from app.state import apply_routing


class DomainEngine:
    def __init__(self, repositories):
        self.inventory = SeatInventory()
        self.services = {
            "flights": FlightsService(repositories.flights, self.inventory),
            "shopping": ShoppingService(repositories.products),
            "cinema": CinemaService(repositories.movies, repositories.cinemas,
                                    repositories.showtimes, self.inventory),
        }

    def execute(self, routing, state):
        outcomes = []
        for intent in routing.intents:
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
        # Shared metadata is applied without merging intents a second time.
        apply_routing(state, RoutingResult(category="ambiguous", language=routing.language,
                                           preferences=routing.preferences))
        if routing.domains:
            state.last_active_domain = routing.domains[0] if len(routing.domains) == 1 else None
        return outcomes
