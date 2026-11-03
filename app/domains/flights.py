from datetime import time

from app.domain_models import DomainResult, PendingOperation
from app.domains.common import DomainIssue, by_ids, price_range, resolve_ids, result, same


class FlightsService:
    def __init__(self, repository, inventory):
        self.repo, self.inventory = repository, inventory

    def search(self, p):
        missing = [name for name in ("origin", "destination", "departure_date") if not getattr(p, name)]
        if missing:
            raise DomainIssue("flight_search", missing=missing)
        if p.return_date is not None:
            raise DomainIssue("one_way_only")
        price_range(p)
        try:
            exact = time.fromisoformat(p.departure_time) if p.departure_time else None
            start = time.fromisoformat(p.departure_time_from) if p.departure_time_from else None
            end = time.fromisoformat(p.departure_time_to) if p.departure_time_to else None
        except ValueError:
            raise DomainIssue("invalid_time", status="error") from None
        if start and end and start > end:
            raise DomainIssue("invalid_range", status="error")
        rows = []
        for row in self.repo.list_all():
            if not any(same(p.origin, value) for value in (row.origin.code, row.origin.city)):
                continue
            if not any(same(p.destination, value) for value in (row.destination.code, row.destination.city)):
                continue
            if row.departure_local.date() != p.departure_date:
                continue
            if p.min_price_azn is not None and row.price_azn < p.min_price_azn:
                continue
            if p.max_price_azn is not None and row.price_azn > p.max_price_azn:
                continue
            if p.stops is not None and row.stops != p.stops:
                continue
            if p.airline and not same(p.airline, row.airline):
                continue
            if p.cabin and not same(p.cabin, row.cabin):
                continue
            if p.baggage_kg is not None and row.baggage_kg < p.baggage_kg:
                continue
            departure = row.departure_local.time()
            if exact and departure != exact or start and departure < start or end and departure > end:
                continue
            viewed = self.inventory.view(row)
            if p.passengers is not None and viewed.seats_available < p.passengers:
                continue
            rows.append(viewed)
        sorts = {"price_asc": ("price_azn", False), "price_desc": ("price_azn", True),
                 "stops_asc": ("stops", False), "stops_desc": ("stops", True),
                 "departure_asc": ("departure_local", False), "departure_desc": ("departure_local", True),
                 "airline_asc": ("airline", False), "airline_desc": ("airline", True)}
        if p.sort_by:
            if p.sort_by not in sorts:
                raise DomainIssue("invalid_sort", status="error")
            field, reverse = sorts[p.sort_by]
            rows.sort(key=lambda row: getattr(row, field), reverse=reverse)
        return rows

    def execute(self, extracted, session):
        ctx, delta = session.flights, extracted.parameters
        action = extracted.intent
        if action == "follow_up":
            action = ctx.pending.action if ctx.pending else "details" if delta.reference or delta.result_positions else "search"
        if action == "resume" and ctx.selected_ids:
            action = "details"
        if action in {"search", "filter", "sort", "resume"}:
            ctx.pending = None
            rows = self.search(ctx.parameters)
            ctx.last_result_ids, ctx.selected_ids = [row.id for row in rows], []
            return result("flights", action, "flights", rows)
        if action not in {"details", "compare", "availability", "reserve"}:
            raise DomainIssue("unsupported_operation", status="error")
        pending = ctx.pending if ctx.pending and ctx.pending.action == action else None
        explicit = delta.flight_ids
        if delta.flight_number and explicit is None:
            explicit = [row.id for row in self.repo.list_all() if same(row.flight_number, delta.flight_number)]
            if not explicit:
                return result("flights", action, "flights", [])
        ids = resolve_ids(self.repo, explicit, delta.result_positions,
                          None if extracted.intent == "resume" else delta.reference,
                          ctx.last_result_ids, pending.ids if pending and pending.ids else ctx.selected_ids)
        if action == "compare" and not ids and not delta.reference:
            ids = ctx.last_result_ids.copy()
        quantity = delta.passengers or (pending.quantity if pending else None)
        if action == "reserve" and (len(ids) != 1 or quantity is None):
            ctx.pending = PendingOperation(action=action, ids=ids, quantity=quantity)
            raise DomainIssue("flight_reserve", missing=(["flight_id"] if len(ids) != 1 else []) +
                              (["passengers"] if quantity is None else []))
        if not ids or action == "compare" and len(ids) < 2:
            raise DomainIssue("compare_items" if action == "compare" else "choose_item")
        rows = by_ids(self.repo, ids)
        for row in rows:
            if delta.departure_date and row.departure_local.date() != delta.departure_date \
                    or delta.origin and not any(same(delta.origin, value) for value in (row.origin.city, row.origin.code)) \
                    or delta.destination and not any(same(delta.destination, value) for value in (row.destination.city, row.destination.code)) \
                    or delta.stops is not None and row.stops != delta.stops \
                    or delta.airline and not same(row.airline, delta.airline) \
                    or delta.max_price_azn is not None and row.price_azn > delta.max_price_azn \
                    or delta.min_price_azn is not None and row.price_azn < delta.min_price_azn:
                raise DomainIssue("selection_mismatch")
        ctx.selected_ids = ids
        if action == "reserve":
            booking = self.inventory.reserve(rows[0], quantity)
            ctx.reservations.append(booking)
            ctx.pending = None
            return DomainResult(domain="flights", operation=action, code="reserved",
                                data={"reservation": booking.model_dump(mode="json"),
                                      "flights": [self.inventory.view(rows[0]).model_dump(mode="json")]})
        ctx.pending = None
        ctx.last_result_ids = ids.copy()
        return result("flights", action, "flights", [self.inventory.view(row) for row in rows])
