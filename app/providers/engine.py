"""Bridge async providers into the existing synchronous, transactional chat flow."""

from contextlib import nullcontext

from app.domain_models import DomainResult
from app.domains.common import DomainIssue
from app.domains.engine import DomainEngine
from app.providers.aviasales import AviasalesProvider
from app.providers.birmarket import BirmarketProvider
from app.providers.buywhere import BuyWhereProvider
from app.providers.cinema_service import CinemaProviderService
from app.providers.ebay import EbayProvider
from app.providers.http import ProviderFailure, ProviderHTTP, run_provider
from app.providers.models import ProviderResult, Provenance, unavailable
from app.providers.references import saved_ids


class NoInventory:
    def transaction(self):
        return nullcontext()


class ProviderDomainEngine(DomainEngine):
    def __init__(self, settings, http=None):
        self.inventory = NoInventory()
        self.http = http or ProviderHTTP(timeout=settings.provider_timeout_seconds,
            retries=settings.provider_retries, ttl=settings.provider_cache_ttl,
            connect_timeout=settings.provider_connect_timeout_seconds,
            request_budget=settings.provider_request_budget_seconds, domain_budget=settings.provider_domain_budget_seconds)
        if settings.shopping_provider not in {"auto", "birmarket", "ebay", "buywhere"}:
            raise ValueError("SHOPPING_PROVIDER must be auto, birmarket, ebay, or buywhere")
        flights = AviasalesProvider(self.http, settings.travelpayouts_token, settings.flight_currency, settings.flight_market)
        if settings.shopping_provider == "birmarket":
            shopping = BirmarketProvider()
        elif settings.shopping_provider == "ebay":
            shopping = EbayProvider(self.http, settings.ebay_token, settings.ebay_marketplace,
                                   settings.ebay_client_id, settings.ebay_client_secret)
        else:
            shopping = BuyWhereProvider(self.http, settings.buywhere_token, settings.buywhere_market)
        self.services = {domain: ProviderService(domain, provider, self.http) for domain, provider in
                         (("flights", flights), ("shopping", shopping))}
        self.services["cinema"] = CinemaProviderService(self.http, settings)


class ProviderService:
    def __init__(self, domain, provider, http=None):
        self.domain, self.provider = domain, provider
        self.http = http or provider.http

    def execute(self, intent, state):
        try:
            return run_provider(self.http.run_domain(self.run(intent, state), self.domain))
        except ProviderFailure as exc:
            ctx = getattr(state, self.domain)
            ctx.provider_snapshot, ctx.last_result_ids, ctx.selected_ids, ctx.pending = {}, [], [], None
            key = "flights" if self.domain == "flights" else "products"
            url = "https://www.aviasales.com/" if self.domain == "flights" else getattr(self.provider, "website", "https://buywhere.ai/")
            return self.outcome(intent.intent, key, unavailable(self.provider.name, url,
                "This provider took too long. Please try again shortly.", exc.code, exc.retry_after))

    async def run(self, intent, state):
        ctx = getattr(state, self.domain)
        p, delta, action = ctx.parameters, intent.parameters, intent.intent
        key = {"flights": "flights", "shopping": "products", "cinema": "movies"}[self.domain]
        ids_field = {"flights": "flight_ids", "shopping": "product_ids", "cinema": "movie_ids"}[self.domain]
        if action == "follow_up":
            action = "details" if getattr(delta, ids_field) or delta.reference or delta.result_positions else "search"
        # An API for cached fares/metadata grants no booking, inventory or cart authority.
        if action in {"reserve", "availability", "cart_add", "cart_remove", "cart_view"}:
            if self.domain == "shopping" and isinstance(self.provider, BirmarketProvider):
                response = self.provider.authorization_required()
            else:
                response = unavailable(self.provider.name, "https://www.aviasales.com/" if self.domain == "flights" else getattr(self.provider, "website", "https://www.ebay.com/"),
                    "This provider cannot verify availability or perform reservations, purchases or cart operations.", "unsupported_operation")
            return self.outcome(action, key, response)
        if action not in {"search", "filter", "sort", "resume", "details", "compare"}:
            raise DomainIssue("unsupported_operation", status="error")
        if isinstance(self.provider, BirmarketProvider):
            response = await self.provider.search(p)
            ctx.provider_snapshot = response.model_dump(mode="json")
            ctx.last_result_ids, ctx.selected_ids, ctx.pending = [], [], None
            return self.outcome(action, key, response)
        if action in {"details", "compare"} or action == "resume" and ctx.selected_ids:
            saved = ctx.provider_snapshot
            ids = saved_ids(ctx, getattr(delta, ids_field), delta.result_positions, delta.reference, action == "compare")
            rows = saved.get("items", [])
            known = {r["id"]: r for r in rows}
            if not ids:
                raise DomainIssue("compare_items" if action == "compare" else "choose_item")
            else:
                if action == "compare" and len(ids) < 2:
                    raise DomainIssue("compare_items")
                if any(identifier not in known for identifier in ids):
                    raise DomainIssue("unknown_id")
                source = Provenance.model_validate(saved["source"])
                source.status, source.local_cache_hit = "cached", True
                selected = [known[i] for i in ids]
                if self.domain == "flights":
                    try:
                        await self.validate_flight_selection(selected, delta)
                    except ProviderFailure as exc:
                        return self.outcome(action, key, unavailable(self.provider.name, source.source_url,
                            "Cannot validate the selected route. Please supply an explicit IATA code.", exc.code, exc.retry_after))
                if self.domain == "shopping" and (isinstance(self.provider, EbayProvider) or
                    isinstance(self.provider, BuyWhereProvider) and self.provider.token) and action != "compare":
                    if len(ids) > 4:
                        raise DomainIssue("choose_item")
                    responses = [await self.provider.details(i) for i in ids]
                    failure = next((r for r in responses if r.error), None)
                    if failure is not None:
                        return self.outcome(action, key, failure)
                    selected = [r.items[0].model_dump(mode="json") for r in responses]
                    source = responses[0].source
                ctx.selected_ids = ids
                ctx.last_result_ids = ids.copy()
                return self.outcome(action, key, ProviderResult(source=source, items=selected, partial=True))
        if self.domain == "flights":
            missing = [name for name in ("origin", "destination", "departure_date") if getattr(p, name) is None]
            if missing:
                raise DomainIssue("flight_search", missing=missing)
        response = await self.provider.search(p)
        # Replace selection context even after a failed/empty new search to avoid stale actions.
        ctx.provider_snapshot = response.model_dump(mode="json")
        ctx.last_result_ids = [r.id for r in response.items]
        ctx.selected_ids, ctx.pending = [], None
        return self.outcome(action, key, response)

    async def validate_flight_selection(self, rows, delta):
        """A follow-up cannot apply new constraints while silently returning an old fare."""
        from datetime import datetime
        from decimal import Decimal
        locations = {field: await self.provider.resolve_iata(getattr(delta, field))
                     for field in ("origin", "destination") if getattr(delta, field)}
        for row in rows:
            if any(value not in {row[field], row.get(field + "_airport")} for field, value in locations.items()):
                raise DomainIssue("selection_mismatch")
            if delta.baggage_kg is not None or delta.cabin:
                raise DomainIssue("unsupported_filter", status="error")
            if delta.currency and delta.currency.upper() != row["price"]["currency"]:
                raise DomainIssue("selection_mismatch")
            if (delta.min_price_azn is not None or delta.max_price_azn is not None) and row["price"]["currency"] != "AZN":
                raise DomainIssue("currency_filter_mismatch", status="error")
            if (delta.departure_date and datetime.fromisoformat(row["departure_at"]).date() != delta.departure_date
                or delta.return_date and (not row.get("return_at") or datetime.fromisoformat(row["return_at"]).date() != delta.return_date)
                or delta.stops is not None and row.get("stops") != delta.stops
                or delta.airline and (row.get("airline") or "").casefold() != delta.airline.casefold()
                or delta.min_price_azn is not None and Decimal(row["price"]["amount"]) < Decimal(str(delta.min_price_azn))
                or delta.max_price_azn is not None and Decimal(row["price"]["amount"]) > Decimal(str(delta.max_price_azn))):
                raise DomainIssue("selection_mismatch")

    def outcome(self, action, key, response):
        serialized = response.model_dump(mode="json")
        data = {key: serialized["items"], "provider": serialized["source"], "partial": response.partial}
        if response.pagination:
            data["pagination"] = response.pagination
        if response.error:
            data["provider_error"] = serialized["error"]
        if self.domain == "cinema":
            data.update(showtimes=[], cinemas=[], screening_status="unavailable")
        return DomainResult(domain=self.domain, operation=action,
            status="error" if response.error else "ok" if response.items else "no_results",
            code=response.error.code if response.error else "results", data=data)
