"""Provider contracts and active chat integration; no live network or real tokens."""

import asyncio
import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.providers.aviasales import AviasalesProvider
from app.providers.birmarket import BirmarketProvider
from app.providers.cinema import CinemaPlusProvider, TMDBProvider
from app.providers.ebay import EbayProvider
from app.providers.engine import ProviderDomainEngine
from app.providers.http import ProviderFailure, ProviderHTTP
from app.schemas import CinemaParameters, FlightParameters, ShoppingParameters
from app.state import SessionState
from app.schemas import RoutingResult


def run(awaitable):
    return asyncio.run(awaitable)


def flight_parameters(**changes):
    return FlightParameters.model_validate(dict(origin="GYD", destination="IST", departure_date="2026-12-01", **changes))


def fare(**changes):
    return dict(origin="GYD", destination="IST", origin_airport="GYD", destination_airport="IST",
                departure_at="2026-12-01T10:00:00+04:00", price=120, airline="J2",
                flight_number="75", transfers=0, duration=190, link="/search/GYD0112IST1", **changes)


def transport(handler, **options):
    return ProviderHTTP(transport=httpx.MockTransport(handler), retries=0, **options)


def intent(domain, operation="search", **parameters):
    return RoutingResult.model_validate({"category": domain, "domains": [domain], "intents": [
        {"domain": domain, "intent": operation, "parameters": parameters}]})


def test_flight_request_prices_unknown_facts_and_cache():
    calls = []
    def handler(request):
        calls.append(request)
        assert request.url.path == "/aviasales/v3/prices_for_dates"
        assert request.headers["X-Access-Token"] == "private-token"
        assert "token" not in request.url.params
        assert request.url.params["currency"] == "azn"
        assert request.url.params["departure_at"] == "2026-12-01"
        return httpx.Response(200, json={"success": True, "currency": "azn", "data": [fare()]})
    provider = AviasalesProvider(transport(handler), "private-token")
    first = run(provider.search(flight_parameters()))
    second = run(provider.search(flight_parameters()))
    assert first.source.status == second.source.status == "cached"
    assert first.source.local_cache_hit is False and second.source.local_cache_hit
    assert first.source.fetched_at == second.source.fetched_at and len(calls) == 1
    row = first.items[0]
    assert row.price.amount == 120 and row.price.currency == "AZN"
    assert row.seats_available is row.baggage_kg is row.cabin is None
    assert row.booking_url.startswith("https://www.aviasales.com/")
    assert "private-token" not in first.model_dump_json()


def test_iata_resolution_and_ambiguity():
    def handler(request):
        return httpx.Response(200, json=[{"type": "city", "code": "BAK", "name": "Baku"},
            {"type": "airport", "code": "GYD", "city_name": "Baku", "name": "Heydar Aliyev"}])
    provider = AviasalesProvider(transport(handler), "test")
    assert run(provider.resolve_iata("Baku")) == "BAK"
    assert run(provider.resolve_iata("gyd")) == "GYD"
    with pytest.raises(ProviderFailure, match="iata_required"):
        run(provider.resolve_iata("Unknown place"))
    provider = AviasalesProvider(transport(lambda r: httpx.Response(200, json=[
        {"type": "city", "code": "AAA", "name": "Springfield"},
        {"type": "city", "code": "BBB", "name": "Springfield"}])), "test")
    with pytest.raises(ProviderFailure, match="iata_required"):
        run(provider.resolve_iata("Springfield"))


def test_flight_sort_filter_roundtrip_currency():
    rows = [fare(), {**fare(), "price": 80, "flight_number": "77", "transfers": 1}]
    def handler(request):
        assert request.url.params["one_way"] == "false"
        assert request.url.params["return_at"] == "2026-12-05"
        assert request.url.params["direct"] == "false"
        return httpx.Response(200, json={"success": True, "data": [
            {**r, "return_at": "2026-12-05T12:00:00+03:00"} for r in rows]})
    provider = AviasalesProvider(transport(handler), "test")
    result = run(provider.search(flight_parameters(return_date="2026-12-05", sort_by="price_desc")))
    assert [r.price.amount for r in result.items] == [120, 80]
    assert all(r.duration_min is None for r in result.items)  # no invented outbound duration
    result = run(provider.search(flight_parameters(return_date="2026-12-05", max_price_azn=100)))
    assert len(result.items) == 1 and result.items[0].stops == 1
    result = run(provider.search(flight_parameters(currency="USD", max_price_azn=100)))
    assert result.error.code == "currency_filter_mismatch"
    result = run(provider.search(flight_parameters(baggage_kg=20)))
    assert result.error.code == "unsupported_filter"


def test_flight_decimal_budget_boundary():
    provider = AviasalesProvider(transport(lambda r: httpx.Response(200, json={"success": True,
        "data": [{**fare(), "price": "120.1"}]})), "test")
    result = run(provider.search(flight_parameters(min_price_azn=120.1, max_price_azn=120.1)))
    assert len(result.items) == 1 and str(result.items[0].price.amount) == "120.1"


@pytest.mark.parametrize("payload,code", [
    ({"success": False, "error": "private-secret"}, "upstream_error"),
    ({"success": True, "data": {}}, "invalid_response"),
    ({"success": True, "data": [{"price": -1}]}, "invalid_response"),
    ({"success": True, "currency": "rub", "data": []}, "currency_mismatch"),
])
def test_flight_malformed_provider_payload(payload, code):
    result = run(AviasalesProvider(transport(lambda r: httpx.Response(200, json=payload)), "test").search(flight_parameters()))
    assert result.error.code == code and result.source.status == "unavailable"
    assert "private-secret" not in result.model_dump_json()


def test_missing_token_empty_results_and_no_stale_fallback():
    provider = AviasalesProvider(transport(lambda r: pytest.fail("Unexpected HTTP")))
    assert run(provider.search(flight_parameters())).error.code == "missing_credentials"
    calls, clock = [], [0]
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"success": True, "data": []}) if len(calls) == 1 else httpx.Response(503)
    provider = AviasalesProvider(transport(handler, clock=lambda: clock[0], ttl=10), "test")
    first = run(provider.search(flight_parameters()))
    assert not first.items and first.error is None
    clock[0] = 11
    failed = run(provider.search(flight_parameters()))
    assert failed.error and failed.source.status == "unavailable"


def test_timeout_retries_rate_limit_and_authentication():
    calls, delays = [], []
    async def sleep(delay):
        delays.append(delay)
    def handler(request):
        calls.append(request)
        if len(calls) < 3:
            raise httpx.ReadTimeout("secret-url", request=request)
        return httpx.Response(200, json={"ok": True})
    http = ProviderHTTP(transport=httpx.MockTransport(handler), retries=2, sleep=sleep)
    assert run(http.get("https://example.test/health")).data == {"ok": True}
    assert len(calls) == 3 and delays == [0.25, 0.5]
    calls.clear()
    def limited(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "42"})
    http = transport(limited)
    for _ in range(2):
        with pytest.raises(ProviderFailure) as exc:
            run(http.get("https://example.test/search"))
        assert exc.value.code == "rate_limited" and exc.value.retry_after >= 41
    assert len(calls) == 1
    http = transport(lambda r: httpx.Response(401, text="private-token"))
    with pytest.raises(ProviderFailure, match="credentials_or_permissions"):
        run(http.get("https://other.test/search"))


def test_birmarket_has_no_fabricated_public_api():
    provider = BirmarketProvider()
    for result in (run(provider.search(ShoppingParameters(query="phone"))), run(provider.categories()), run(provider.details("P001"))):
        assert result.source.provider == "Birmarket" and result.source.status == "unavailable"
        assert not result.items and result.error.code == "authorization_required"
    assert not any(provider.capabilities.values())


def test_unavailable_adapters_report_authorization_for_detail_requests():
    engine = ProviderDomainEngine(Settings(shopping_provider="birmarket"))
    state = SessionState()
    for domain, parameters in (("shopping", {"product_ids": ["P001"]}),
                               ("cinema", {"movie_ids": ["M001"]})):
        result = engine.execute(intent(domain, "details", **parameters), state)[0]
        assert result.code == ("authorization_required" if domain == "shopping" else "unknown_id")
        if domain == "shopping":
            assert result.data["provider"]["status"] == "unavailable"


def test_separate_tmdb_metadata():
    calls = []
    def handler(request):
        calls.append(request)
        assert request.headers["Authorization"] == "Bearer test"
        assert request.url.path == "/3/search/movie" and request.url.params["query"] == "Dune"
        return httpx.Response(200, json={"results": [{"id": 438631, "title": "Dune", "overview": "Desert world",
            "vote_average": 7.8, "original_language": "en", "poster_path": "/poster.jpg"}]})
    provider = TMDBProvider(transport(handler), "test")
    first = run(provider.search(CinemaParameters(movie_title="Dune")))
    second = run(provider.search(CinemaParameters(movie_title="Dune")))
    assert first.source.status == "live" and second.source.status == "cached" and len(calls) == 1
    assert first.source.provider == "TMDB" and "not confirmed CinemaPlus" in first.source.notice
    assert first.items[0].confirmed_cinemaplus_screening is False
    assert first.items[0].duration_min is None
    assert first.items[0].poster_url == "https://image.tmdb.org/t/p/w500/poster.jpg"


def test_tmdb_details_and_failures():
    provider = TMDBProvider(transport(lambda r: httpx.Response(200, json={"id": 11, "title": "Star Wars", "runtime": 121,
        "genres": [{"id": 878, "name": "Science Fiction"}]})), "test")
    details = run(provider.details("TMDB-11"))
    assert details.items[0].duration_min == 121 and details.items[0].genre == ["Science Fiction"]
    assert run(provider.details("../../private")).error.code == "unknown_id"
    assert run(TMDBProvider(transport(lambda r: pytest.fail("HTTP without credentials"))).search(CinemaParameters())).error.code == "missing_credentials"
    for payload in ({"results": {}}, {"results": [{"id": "bad", "title": "Bad"}]}):
        result = run(TMDBProvider(transport(lambda r: httpx.Response(200, json=payload)), "test").search(CinemaParameters()))
        assert result.error.code == "invalid_response"


def test_tmdb_genre_filter_uses_official_genre_catalog():
    paths = []
    def handler(request):
        paths.append(request.url.path)
        if request.url.path.endswith("/genre/movie/list"):
            return httpx.Response(200, json={"genres": [{"id": 878, "name": "Science Fiction"}]})
        return httpx.Response(200, json={"results": [{"id": 11, "title": "Star Wars", "genre_ids": [878]},
            {"id": 12, "title": "Another film", "genre_ids": [35]}]})
    provider = TMDBProvider(transport(handler), "test")
    result = run(provider.search(CinemaParameters(genre="sci-fi")))
    assert [r.id for r in result.items] == ["TMDB-11"]
    assert paths == ["/3/discover/movie", "/3/genre/movie/list"]


@pytest.mark.parametrize("message,domain", [("Reserve 2 tickets for movie TMDB-11", "cinema"),
    ("Reserve flight AV-0123456789abcdef for 2 passengers", "flights")])
def test_local_provider_ids_do_not_look_like_negative_quantities(message, domain):
    from app.fallback import LocalRouter
    from app.repositories import Repositories
    route = LocalRouter(Repositories.empty()).route(message, SessionState())
    assert route.category.value == domain and route.intents[0].intent == "reserve"


def test_optional_ebay_is_not_relabeled_birmarket():
    def handler(request):
        assert request.url.host == "api.ebay.com" and request.url.params["sort"] == "price"
        return httpx.Response(200, json={"total": 1, "itemSummaries": [{"itemId": "v1|123|0", "title": "Headphones",
            "price": {"value": "12.34", "currency": "USD"}, "itemWebUrl": "https://www.ebay.com/itm/123"}]})
    provider = EbayProvider(transport(handler), "test")
    result = run(provider.search(ShoppingParameters(query="headphones", sort_by="price_asc")))
    assert result.source.provider == "eBay" and result.items[0].price.currency == "USD"
    assert result.items[0].in_stock is None
    assert run(provider.search(ShoppingParameters(query="headphones", max_price_azn=20))).error.code == "unsupported_filter"


def test_provider_engine_comparisons_state_and_no_reservations():
    http = transport(lambda r: httpx.Response(200, json={"success": True, "data": [fare(),
        {**fare(), "price": 150, "flight_number": "88"}]}))
    engine = ProviderDomainEngine(Settings(travelpayouts_token="test", shopping_provider="birmarket"), http)
    state = SessionState()
    first = engine.execute(intent("flights", origin="GYD", destination="IST", departure_date="2026-12-01"), state)[0]
    ids = [r["id"] for r in first.data["flights"]]
    assert state.flights.last_result_ids == ids
    compared = engine.execute(intent("flights", "compare", flight_ids=ids), state)[0]
    assert len(compared.data["flights"]) == 2 and compared.data["provider"]["status"] == "cached"
    chosen = engine.execute(intent("flights", "details", reference="the cheaper one"), state)[0]
    assert chosen.data["flights"][0]["price"]["amount"] == "120"
    booking = engine.execute(intent("flights", "reserve", flight_ids=[ids[0]], passengers=2), state)[0]
    assert booking.status == "error" and not state.flights.reservations
    assert "reservation" not in booking.data
    shopping = engine.execute(intent("shopping", query="phone"), state)[0]
    assert shopping.code == "authorization_required" and state.flights.last_result_ids == ids
    assert engine.execute(intent("flights", "details", flight_ids=["F001"]), state)[0].code == "unknown_id"
    mismatch = engine.execute(intent("flights", "details", flight_ids=[ids[0]], stops=1), state)[0]
    assert mismatch.code == "selection_mismatch"
    mismatch = engine.execute(intent("flights", "details", flight_ids=[ids[0]], origin="DXB"), state)[0]
    assert mismatch.code == "selection_mismatch"


def test_active_app_never_loads_fixtures_and_preserves_history(tmp_path, monkeypatch):
    def forbidden(*args):
        pytest.fail("Provider mode attempted to load fixture JSON")
    monkeypatch.setattr("app.repositories.Repositories.from_json", forbidden)
    settings = Settings(routing_mode="offline", data_dir=tmp_path, shopping_provider="birmarket")
    with TestClient(create_app(settings)) as client:
        client.app.state.chat_service.engine.http.transport = httpx.MockTransport(lambda r: httpx.Response(403))
        assert client.get("/health").json() == {"status": "ok"}
        assert client.get("/api/client").json()["data_mode"] == "providers"
        first = client.post("/api/chat", json={"message": "Show shopping products"}).json()
        assert first["results"][0]["data"]["provider"]["status"] == "unavailable"
        second = client.post("/api/chat", json={"message": "Show movies", "session_id": first["session_id"]}).json()
        assert len(second["state"]["history"]) == 4
        assert second["state"]["shopping"]["intent"] == "search"
        assert second["results"][0]["data"]["showtimes"] == []
        assert second["reference_date"] == settings.reference_date().isoformat()
        assert "TRAVELPAYOUTS_API_TOKEN" not in client.get("/api/providers").text


def test_environment_credentials_and_no_required_dotenv(monkeypatch):
    monkeypatch.setattr("app.config.load_dotenv", lambda *a, **kw: None)
    monkeypatch.setenv("TRAVELPAYOUTS_API_TOKEN", " flight-secret ")
    monkeypatch.setenv("TMDB_READ_ACCESS_TOKEN", " movie-secret ")
    monkeypatch.setenv("SHOPPING_PROVIDER", "birmarket")
    monkeypatch.delenv("SUPERCHAT_DATA_MODE", raising=False)
    settings = Settings.from_env()
    assert settings.data_mode == "providers" and settings.travelpayouts_token == "flight-secret"
    assert settings.tmdb_token == "movie-secret" and "secret" not in repr(settings)
