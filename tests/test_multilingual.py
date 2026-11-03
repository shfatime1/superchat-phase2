"""Cross-language parity, real provider contracts, and stateful language changes."""
from datetime import date

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.fallback import LocalRouter
from app.languages import detect_language, normalize_text
from app.main import create_app
from app.repositories import Repositories
from app.routing import GeminiRouter
from app.schemas import Domain, ShoppingParameters
from app.state import SessionState, apply_routing
from conftest import route


SHOPPING = [
    ("500$ dan ucuz notebooklar", "az"), ("laptops under $500", "en"),
    ("laptops is price under 500$", "en"), ("Ноутбуки до 500 долларов", "ru"),
    ("Покажи laptops до $500", "ru"), ("500 USD-dan ucuz noutbuklar göstər", "az"),
]
FLIGHTS = [("Bakıdan İstanbula sabah uçuşlar", "az"),
           ("Flights from Baku to Istanbul tomorrow", "en"), ("Рейсы из Баку в Стамбул завтра", "ru")]
CINEMA = [("Bu gün CinemaPlus filmlər göstər", "az"),
          ("Show CinemaPlus movies today", "en"), ("Покажи фильмы CinemaPlus сегодня", "ru")]


@pytest.mark.parametrize("mode", ["local", "gemini"])
@pytest.mark.parametrize("message,language", SHOPPING)
def test_equivalent_multilingual_shopping_budgets(message, language, mode, gemini):
    state = SessionState()
    if mode == "local":
        router = LocalRouter(Repositories.empty())
    else:
        _, enqueue = gemini
        enqueue(route("shopping", "shopping", {"query": "notebooks", "max_price_azn": 500}))
        router = GeminiRouter(Settings(api_key="test"))
    result = router.route(message, state)
    assert result.category.value == "shopping" and result.language == language
    p = result.intents[0].parameters
    assert p.query == "laptops" and p.currency == "USD" and p.max_price == 500
    assert p.max_price_azn is None


@pytest.mark.parametrize("message,language", FLIGHTS)
def test_multilingual_flight_routes_dates(message, language):
    result = LocalRouter(Repositories.empty(), lambda: date(2026, 11, 3)).route(message, SessionState())
    assert result.category.value == "flights" and result.language == language
    p = result.intents[0].parameters
    assert p.origin == "baku" and p.destination == "istanbul" and p.departure_date == date(2026, 11, 4)


@pytest.mark.parametrize("message,language", CINEMA)
def test_multilingual_cinema_does_not_infer_screening_language(message, language):
    result = LocalRouter(Repositories.empty(), lambda: date(2026, 11, 3)).route(message, SessionState())
    assert result.category.value == "cinema" and result.language == language
    assert result.intents[0].parameters.date == date(2026, 11, 3)
    assert result.intents[0].parameters.language is None


@pytest.mark.parametrize("message,language", [
    ("Sabah Bakıdan İstanbula uçuşlar və 500$ dan ucuz notebooklar", "az"),
    ("Flights from Baku to Istanbul tomorrow and laptops under $500", "en"),
    ("Рейсы из Баку в Стамбул завтра и ноутбуки до 500 долларов", "ru"),
])
@pytest.mark.parametrize("mode", ["local", "gemini"])
def test_mixed_multilingual_clauses_keep_dates_and_currencies(message, language, mode, gemini):
    if mode == "local":
        router = LocalRouter(Repositories.empty(), lambda: date(2026, 11, 3))
    else:
        _, enqueue = gemini
        enqueue({"category": "mixed", "domains": ["flights", "shopping"], "intents": [
            {"domain": "flights", "intent": "search", "parameters": {"origin": "Baku", "destination": "Istanbul"}},
            {"domain": "shopping", "intent": "search", "parameters": {"query": "notebooks"}}]})
        router = GeminiRouter(Settings(data_mode="fixtures", api_key="test"))
    result = router.route(message, SessionState())
    assert result.category.value == "mixed" and result.language == language
    flight, shopping = result.intents
    assert flight.parameters.departure_date is not None and flight.parameters.currency is None
    assert shopping.parameters.query == "laptops" and shopping.parameters.max_price == 500 and shopping.parameters.currency == "USD"


def test_language_changes_do_not_erase_domain_context_or_selection():
    router = LocalRouter(Repositories.empty())
    state = SessionState()
    for message, language in [("Show laptops under $500", "en"), ("100$ dan ucuz", "az"), ("Подробнее второй", "ru")]:
        result = router.route(message, state)
        assert result.language == language
        apply_routing(state, result)
    assert state.shopping.parameters.query == "laptops" and state.shopping.parameters.max_price == 100
    assert state.shopping.parameters.result_positions == [2]
    assert state.language == "ru"
    result = router.route("Show headphones", state)
    assert result.intents[0].reset_context and result.language == "en"
    apply_routing(state, result)
    assert state.shopping.parameters.max_price is None and state.shopping.parameters.result_positions is None


@pytest.mark.parametrize("language,message,word", [("az", "500$ dan ucuz notebooklar", "Satıcı"),
    ("en", "laptops under $500", "Retailer"), ("ru", "Ноутбуки до 500 долларов", "Продавец")])
def test_real_shape_null_categories_localized_results_and_filters(language, message, word):
    app = create_app(Settings(routing_mode="offline"))
    def handler(request):
        assert request.url.params["q"] == "laptops" and request.url.params["currency"] == "USD"
        assert request.url.params["max_price"] == "500.0"
        return httpx.Response(200, json={"data": [
            {"id": "1", "title": "Dell Laptop", "category_path": None, "price": {"amount": 499, "currency": "USD"}, "merchant_name": "Retailer", "url": "https://shop.example/dell-laptop"},
            {"id": "2", "title": "Laptop stand", "category_path": None, "price": {"amount": 50, "currency": "USD"}, "url": "https://shop.example/laptop-stand"},
            {"id": "3", "title": "Laptop expensive", "price": {"amount": 501, "currency": "USD"}, "url": "https://shop.example/laptop"},
            {"id": "4", "title": "Broken", "price": {"amount": -1, "currency": "USD"}, "url": "https://shop.example/broken"},
        ]})
    with TestClient(app) as client:
        app.state.chat_service.engine.http.transport = httpx.MockTransport(handler)
        response = client.post("/api/chat", json={"message": message}).json()
        assert response["routing"]["language"] == language
        assert response["results"][0]["status"] == "ok" and word in response["message"]
        rows = response["results"][0]["data"]["products"]
        assert len(rows) == 1 and rows[0]["price"]["amount"] == "499"
        before = response["state"]["shopping"]["parameters"]
        switched = client.post("/api/chat", json={"message": "English please", "session_id": response["session_id"]}).json()
        assert switched["state"]["shopping"]["parameters"] == before
        assert switched["message"] == "Let’s continue in English."


def test_explicit_interface_language_is_validated_and_applies_to_clarifications():
    with TestClient(create_app(Settings(routing_mode="offline"))) as client:
        answer = client.post("/api/chat", json={"message": "Flights", "language": "ru"}).json()
        assert answer["routing"]["language"] == "ru" and "Укажите" in answer["message"]
        assert client.post("/api/chat", json={"message": "Flights", "language": "bad"}).status_code == 422


@pytest.mark.parametrize("message", ["Ноутбуки до 500 долларов", "500$ dan ucuz notebooklar", "Bakıdan İstanbula sabah uçuşlar"])
def test_normalization_is_idempotent(message):
    semantic = normalize_text(message)
    assert normalize_text(semantic) == semantic


def test_quoted_names_and_provider_identifiers_are_not_translated():
    semantic = normalize_text('Покажи "Tomorrow" CP-AbCd и BW-ProductABC')
    assert '"Tomorrow"' in semantic and 'CP-AbCd' in semantic and 'BW-ProductABC' in semantic
    from app.dates import date_expression
    assert date_expression('Show movie "Tomorrow"') is None
    result = LocalRouter(Repositories.empty()).route("Show details for product BW-ProductABC", SessionState())
    assert result.intents[0].parameters.product_ids == ["BW-ProductABC"]


@pytest.mark.parametrize("language,flight_word,cinema_word", [("en", "cached", "Official schedule"),
    ("az", "keşlənmiş", "Rəsmi cədvəl"), ("ru", "кешированные", "Официальное расписание")])
def test_localized_provider_replies_preserve_factual_prices_links_ids(language, flight_word, cinema_word):
    from app.domain_models import DomainResult
    from app.provider_locale import localize_outcomes
    from app.responses import render
    flight = DomainResult(domain="flights", operation="search", data={
        "provider": {"provider": "Aviasales / Travelpayouts", "status": "cached", "notice": "Cached fares"},
        "flights": [{"id": "AV-abc", "origin": "GYD", "destination": "IST", "departure_at": "2026-12-01T10:00:00+04:00",
            "price": {"amount": "120.00", "currency": "USD"}, "booking_url": "https://www.aviasales.com/search/1"}]})
    cinema = DomainResult(domain="cinema", operation="search", data={
        "provider": {"provider": "CinemaPlus Azerbaijan", "status": "live", "notice": "Official listings"},
        "movies": [{"id": "CP-44", "title": "44", "movie_url": "https://cinemastercard.az/en/films/44/",
            "metadata_url": "https://cinemastercard.az/en/films/44/", "showtimes_url": "https://cinemastercard.az/en/films/44/#sessions"}]})
    localize_outcomes([flight, cinema], language)
    first, second = render(flight, language), render(cinema, language)
    assert flight_word in first and "120.00 USD" in first and "AV-abc" in first
    assert cinema_word in second and "CP-44" in second and "https://cinemastercard.az/en/films/44/#sessions" in second


def test_gemini_keeps_original_multilingual_request_and_fallback_retains_language(gemini):
    import json
    generate, enqueue = gemini
    message = "500$ dan ucuz notebooklar"
    enqueue(route("shopping", "shopping", {"query": "laptops", "currency": "USD", "max_price": 500}, language="en"))
    result = GeminiRouter(Settings(api_key="test")).route(message, SessionState())
    assert result.language == "az" and result.source == "gemini"
    assert json.loads(generate.call_args.kwargs["contents"])["message"] == message
    from app.fallback import ResilientRouter
    enqueue(RuntimeError("simulated outage"))
    result = ResilientRouter(Settings(api_key="test"), Repositories.empty()).route(message, SessionState())
    assert result.source == "local" and result.language == "az"
    assert result.intents[0].parameters.max_price == 500


def test_reply_language_instruction_does_not_drop_a_short_product_request(gemini):
    _, enqueue = gemini
    enqueue(route("shopping", "shopping", {"query": "laptops"}))
    with TestClient(create_app(Settings(api_key="test", routing_mode="strict"))) as client:
        client.app.state.chat_service.engine.http.transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"data": []}))
        body = client.post("/api/chat", json={"message": "Answer in Russian and show laptops"}).json()
        assert body["routing"]["language"] == "ru" and body["results"][0]["domain"] == "shopping"
        assert "Подходящих" in body["message"]
