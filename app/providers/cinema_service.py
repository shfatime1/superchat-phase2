"""Cinema-specific orchestration: official public listings first, TMDB only as fallback."""

import asyncio

from app.domain_models import DomainResult
from app.domains.common import DomainIssue
from app.cinema_queries import normalized_cinema_parameters
from app.providers.cinema import TMDBProvider
from app.providers.cinemaplus import CinemaPlusPublicProvider, HOME
from app.providers.models import Provenance, ProviderResult, unavailable


class CinemaProviderService:
    def __init__(self, http, settings):
        if settings.cinema_provider not in {"auto", "cinemaplus", "tmdb"}:
            raise ValueError("CINEMA_PROVIDER must be auto, cinemaplus, or tmdb")
        self.primary, self.metadata = CinemaPlusPublicProvider(http), TMDBProvider(http, settings.tmdb_token)
        self.mode = settings.cinema_provider

    def execute(self, intent, state):
        return asyncio.run(self.run(intent, state))

    async def run(self, intent, state):
        ctx, delta, action = state.cinema, intent.parameters, intent.intent
        # Clean previously saved chain/catalog labels as well as fresh extraction.
        p = ctx.parameters = normalized_cinema_parameters(ctx.parameters)
        if action == "follow_up":
            action = "details" if delta.movie_ids or delta.result_positions or delta.reference else "search"
        if action in {"reserve", "availability", "cart_add", "cart_remove", "cart_view"}:
            response = unavailable("CinemaPlus Azerbaijan", HOME,
                "CinemaPlus public pages do not verify seat availability or reserve tickets. "
                "Open the official movie/showtime page for seats, final prices and purchase.",
                "seat_availability_unavailable" if action == "availability" else "unsupported_operation")
            return self.outcome(action, response)
        if action not in {"search", "filter", "sort", "details", "compare", "resume"}:
            raise DomainIssue("unsupported_operation", status="error")
        selected = None
        if action in {"details", "compare"} or action == "resume" and ctx.selected_ids:
            ids = delta.movie_ids
            if delta.result_positions:
                if any(i < 1 or i > len(ctx.last_result_ids) for i in delta.result_positions):
                    raise DomainIssue("invalid_selection")
                ids = [ctx.last_result_ids[i - 1] for i in delta.result_positions]
            if not ids and delta.reference:
                if delta.reference.casefold() in {"it", "that", "this", "the one"}:
                    ids = ctx.selected_ids or (ctx.last_result_ids if len(ctx.last_result_ids) == 1 else [])
                else:
                    raise DomainIssue("choose_item")
            ids = list(dict.fromkeys(ids or (ctx.last_result_ids if action == "compare" else ctx.selected_ids)))
            if not ids:
                discovery = p.movie_title or action != "compare" and (p.date or p.time or p.cinema_name or p.cinema_ids)
                if not discovery:
                    raise DomainIssue("compare_items" if action == "compare" else "choose_item")
                action = "search"
            else:
                if action == "compare" and len(ids) < 2:
                    raise DomainIssue("compare_items")
                if len(ids) > 4:
                    raise DomainIssue("choose_item")
                sources = {"tmdb" if i.startswith("TMDB-") else "cinemaplus" if i.startswith("CP-") else "unknown" for i in ids}
                if "unknown" in sources or len(sources) > 1:
                    raise DomainIssue("unknown_id")
                client = self.metadata if sources == {"tmdb"} else self.primary
                responses = [await client.details(i) for i in ids]
                failed = next((r for r in responses if r.error), None)
                if failed is not None:
                    return self.outcome(action, failed)
                selected = responses[0]
                selected.items = [m for response in responses for m in response.items]
                if hasattr(selected, "showtimes"):
                    selected.showtimes = [s for response in responses for s in response.showtimes]
                    selected.cinemas = list({c.id: c for response in responses for c in response.cinemas}.values())
                    self.filter_schedule(selected, p)
                source = min((r.source for r in responses), key=lambda s: s.fetched_at)
                selected.source = source.model_copy(update={"status": "cached" if all(r.source.local_cache_hit for r in responses) else "live"})
                ctx.selected_ids = ids
        response = selected
        primary_error = None
        if response is None:
            if self.mode == "tmdb":
                response = await self.metadata.search(p)
            else:
                response = await self.primary.search(p)
                if response.error and self.mode == "auto" and self.metadata.token:
                    primary_error = response
                    response = await self.metadata.search(p)
                    response.source.notice = "Official CinemaPlus public source failed (" + primary_error.error.code + "). " + response.source.notice
            ctx.selected_ids = []
        ctx.provider_snapshot = response.model_dump(mode="json")
        ctx.last_result_ids = [m.id for m in response.items]
        ctx.last_showtime_ids = [s.id for s in getattr(response, "showtimes", [])]
        ctx.selected_showtime_ids, ctx.pending = [], None
        result = self.outcome(action, response)
        if primary_error is not None:
            result.data["primary_provider_error"] = primary_error.error.model_dump(mode="json")
        return result

    @staticmethod
    def filter_schedule(response, p):
        from decimal import Decimal
        p = normalized_cinema_parameters(p)
        sessions = response.showtimes
        if p.date:
            sessions = [s for s in sessions if s.date == p.date]
        if p.cinema_name:
            sessions = [s for s in sessions if p.cinema_name.casefold() in s.cinema_name.casefold()]
        if p.cinema_ids:
            sessions = [s for s in sessions if s.cinema_id in p.cinema_ids]
        if p.time:
            sessions = [s for s in sessions if s.time == p.time]
        if p.max_price_azn is not None:
            sessions = [s for s in sessions if s.price and s.price.amount <= Decimal(str(p.max_price_azn))]
        response.showtimes = sessions
        for movie in response.items:
            movie.confirmed_cinemaplus_screening = any(s.movie_id == movie.id for s in sessions)

    @staticmethod
    def outcome(action, response):
        serialized = response.model_dump(mode="json")
        data = {"movies": serialized["items"], "provider": serialized["source"], "partial": response.partial,
            "cinemas": serialized.get("cinemas", []), "showtimes": serialized.get("showtimes", []),
            "screening_status": serialized.get("screening_status", "unavailable")}
        if response.error:
            data["provider_error"] = serialized["error"]
        return DomainResult(domain="cinema", operation=action, status="error" if response.error else "ok" if response.items else "no_results",
                            code=response.error.code if response.error else "results", data=data)
