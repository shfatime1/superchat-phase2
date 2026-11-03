from datetime import time

from app.domain_models import DomainResult, PendingOperation
from app.domains.common import DomainIssue, by_ids, resolve_ids, result, same


class CinemaService:
    def __init__(self, movies, cinemas, showtimes, inventory):
        self.movies, self.cinemas, self.showtimes, self.inventory = movies, cinemas, showtimes, inventory

    def search(self, p, movie_ids=None):
        movies = by_ids(self.movies, movie_ids) if movie_ids is not None else self.movies.list_all()
        movies = [row for row in movies
                  if (not p.movie_title or p.movie_title.casefold() in row.title.casefold())
                  and (not p.genre or any(same(p.genre, genre) for genre in row.genre))
                  and (not p.language or same(p.language, row.language))
                  and (p.min_rating is None or row.rating >= p.min_rating)]
        cinemas = by_ids(self.cinemas, p.cinema_ids) if p.cinema_ids is not None else self.cinemas.list_all()
        cinemas = [row for row in cinemas
                   if (not p.cinema_name or p.cinema_name.casefold() in row.name.casefold())
                   and (not p.district or same(p.district, row.district))]
        try:
            at_time = time.fromisoformat(p.time) if p.time else None
        except ValueError:
            raise DomainIssue("invalid_time", status="error") from None
        movie_set, cinema_set = {row.id for row in movies}, {row.id for row in cinemas}
        showtimes = [self.inventory.view(row) for row in self.showtimes.list_all()
                     if row.movie_id in movie_set and row.cinema_id in cinema_set
                     and (p.date is None or row.date == p.date)
                     and (at_time is None or row.time == at_time)
                     and (p.max_price_azn is None or row.price_azn <= p.max_price_azn)]
        # With screening constraints, films must have a matching screening, even if sold out.
        if p.date or p.time or p.cinema_name or p.cinema_ids or p.district or p.max_price_azn is not None:
            showing = {row.movie_id for row in showtimes}
            movies = [row for row in movies if row.id in showing]
        if p.sort_by:
            if p.sort_by not in {"rating_desc", "rating_asc", "title_asc"}:
                raise DomainIssue("invalid_sort", status="error")
            movies.sort(key=lambda row: row.title if p.sort_by == "title_asc" else row.rating,
                        reverse=p.sort_by == "rating_desc")
        showtimes.sort(key=lambda row: (row.date, row.time, row.id))
        showing_cinemas = {row.cinema_id for row in showtimes}
        cinemas = [row for row in cinemas if row.id in showing_cinemas]
        return movies, cinemas, showtimes

    def payload(self, operation, movies, cinemas, showtimes):
        outcome = result("cinema", operation, "movies", movies)
        outcome.data.update({"cinemas": [row.model_dump(mode="json") for row in cinemas],
                             "showtimes": [row.model_dump(mode="json") for row in showtimes]})
        return outcome

    def execute(self, extracted, session):
        ctx, delta = session.cinema, extracted.parameters
        action = extracted.intent
        if action == "follow_up":
            action = ctx.pending.action if ctx.pending else "details" if delta.reference or delta.result_positions else "search"
        if action == "resume" and ctx.selected_ids:
            action = "details"
        if action in {"search", "filter", "sort", "resume"}:
            ctx.pending = None
            movies, cinemas, showtimes = self.search(ctx.parameters, delta.movie_ids)
            ctx.last_result_ids, ctx.last_showtime_ids = [row.id for row in movies], [row.id for row in showtimes]
            ctx.selected_ids, ctx.selected_showtime_ids = [], []
            return self.payload(action, movies, cinemas, showtimes)
        if action not in {"details", "availability", "compare", "reserve"}:
            raise DomainIssue("unsupported_operation", status="error")
        pending = ctx.pending if ctx.pending and ctx.pending.action == action else None
        if action == "details" and not (delta.movie_ids or delta.showtime_ids or delta.reference or delta.result_positions
                                         or delta.movie_title or ctx.selected_ids or ctx.last_result_ids):
            movies, cinemas, showtimes = self.search(ctx.parameters)
            ctx.last_result_ids, ctx.last_showtime_ids = [row.id for row in movies], [row.id for row in showtimes]
            return self.payload(action, movies, cinemas, showtimes)
        showtime_selection = delta.showtime_ids
        if extracted.intent == "resume" and ctx.selected_showtime_ids:
            showtime_selection = ctx.selected_showtime_ids
        if showtime_selection is not None or action == "reserve":
            # Positions on a ticket reservation refer to the displayed showtime list.
            ids = resolve_ids(self.showtimes, showtime_selection, delta.result_positions,
                              None if extracted.intent == "resume" else delta.reference,
                              ctx.last_showtime_ids,
                              pending.ids if pending and pending.ids else ctx.selected_showtime_ids)
            if (delta.movie_ids or delta.movie_title or delta.date or delta.cinema_name or delta.cinema_ids or delta.time) \
                    and not (delta.showtime_ids or delta.result_positions or delta.reference):
                _, _, matches = self.search(ctx.parameters, delta.movie_ids or ctx.selected_ids or None)
                ids = [row.id for row in matches]
            quantity = delta.tickets or (pending.quantity if pending else None)
            if action == "reserve" and (len(ids) != 1 or quantity is None):
                ctx.pending = PendingOperation(action=action, ids=ids, quantity=quantity)
                raise DomainIssue("cinema_reserve", missing=(["showtime_id"] if len(ids) != 1 else []) +
                                  (["tickets"] if quantity is None else []))
            if not ids:
                raise DomainIssue("choose_item")
            showtimes = by_ids(self.showtimes, ids)
            if any(delta.date and row.date != delta.date or delta.movie_ids and row.movie_id not in delta.movie_ids
                   or delta.cinema_ids and row.cinema_id not in delta.cinema_ids
                   or delta.time and row.time.isoformat(timespec="minutes") != delta.time for row in showtimes):
                raise DomainIssue("selection_mismatch")
            movies = by_ids(self.movies, [row.movie_id for row in showtimes])
            cinemas = by_ids(self.cinemas, [row.cinema_id for row in showtimes])
            if any(delta.movie_title and delta.movie_title.casefold() not in row.title.casefold() for row in movies) \
                    or any(delta.cinema_name and delta.cinema_name.casefold() not in row.name.casefold() for row in cinemas) \
                    or any(delta.max_price_azn is not None and row.price_azn > delta.max_price_azn for row in showtimes):
                raise DomainIssue("selection_mismatch")
            ctx.selected_showtime_ids, ctx.selected_ids = ids, [row.id for row in movies]
            if action == "reserve":
                booking = self.inventory.reserve(showtimes[0], quantity)
                ctx.reservations.append(booking)
                ctx.pending = None
                outcome = self.payload(action, movies, cinemas, [self.inventory.view(showtimes[0])])
                outcome.code = "reserved"
                outcome.data["reservation"] = booking.model_dump(mode="json")
                return outcome
            return self.payload(action, movies, cinemas, [self.inventory.view(row) for row in showtimes])
        explicit = delta.movie_ids
        if explicit is None and delta.movie_title:
            found, cinemas, showtimes = self.search(ctx.parameters)
            explicit = [row.id for row in found]
            if not explicit:
                ctx.last_result_ids, ctx.last_showtime_ids = [], []
                return self.payload(action, found, cinemas, showtimes)
        ids = resolve_ids(self.movies, explicit, delta.result_positions,
                          None if extracted.intent == "resume" else delta.reference,
                          ctx.last_result_ids, ctx.selected_ids)
        if not ids and (delta.movie_title or delta.genre or delta.date):
            movies, _, _ = self.search(ctx.parameters)
            ids = [row.id for row in movies]
        if action == "compare" and not ids and not delta.reference:
            ids = ctx.last_result_ids.copy()
        if not ids or action == "compare" and len(ids) < 2:
            raise DomainIssue("compare_items" if action == "compare" else "choose_item")
        parameters = ctx.parameters.model_copy(deep=True)
        if delta.movie_ids:
            # An explicit record selection should not be hidden by an older genre/rating filter.
            for field in ("genre", "movie_title", "language", "min_rating"):
                setattr(parameters, field, getattr(delta, field))
        movies, cinemas, showtimes = self.search(parameters, ids)
        ctx.selected_ids, ctx.pending = ids, None
        ctx.last_result_ids = [row.id for row in movies]
        ctx.last_showtime_ids = [row.id for row in showtimes]
        ctx.selected_showtime_ids = []
        return self.payload(action, movies, cinemas, showtimes)
