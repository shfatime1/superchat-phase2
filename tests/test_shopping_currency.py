"""Currency symbols must reach provider filters without becoming AZN budgets."""

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.fallback import LocalRouter
from app.main import create_app
from app.repositories import Repositories
from app.routing import GeminiRouter
from app.schemas import Domain, ShoppingParameters
from app.state import SessionState, apply_routing
from conftest import route


@pytest.mark.parametrize("budget,currency,minimum,maximum", [
    ("under $100", "USD", None, 100),
    ("under $ 100", "USD", None, 100),
    ("under 100$", "USD", None, 100),
    ("under ₼100", "AZN", None, 100),
    ("under 100 ₼", "AZN", None, 100),
    ("under €100", "EUR", None, 100),
    ("under 100 €", "EUR", None, 100),
    ("at least $25.50 and under $100", "USD", 25.5, 100),
    ("above €20 and below €90.99", "EUR", 20, 90.99),
    ("under 100 USD", "USD", None, 100),
    ("under USD 100", "USD", None, 100),
    ("under 100 AZN", "AZN", None, 100),
    ("under $100 SGD", "SGD", None, 100),
])
def test_local_currency_codes_symbols_and_bounds(budget, currency, minimum, maximum):
    result = LocalRouter(Repositories.empty()).route("Show me wireless headphones " + budget, SessionState())
    assert result.category.value == "shopping"
    p = result.intents[0].parameters
    assert p.query == "wireless headphones" and p.currency == currency
    if currency == "AZN":
        assert (p.min_price_azn, p.max_price_azn) == (minimum, maximum)
        assert p.min_price is None and p.max_price is None
    else:
        assert (p.min_price, p.max_price) == (minimum, maximum)
        assert p.min_price_azn is None and p.max_price_azn is None


@pytest.mark.parametrize("budget,currency", [("$100", "USD"), ("₼100", "AZN"), ("€100", "EUR")])
def test_gemini_default_azn_is_corrected_by_stated_symbol(budget, currency, gemini):
    _, enqueue = gemini
    enqueue(route("shopping", "shopping", {"query": "headphones", "currency": "AZN", "max_price_azn": 100}))
    result = GeminiRouter(Settings(api_key="test")).route(
        "Show me wireless headphones under " + budget, SessionState())
    p = result.intents[0].parameters
    assert p.currency == currency and p.query == "wireless headphones"
    assert (p.max_price_azn if currency == "AZN" else p.max_price) == 100
    assert (p.max_price if currency == "AZN" else p.max_price_azn) is None


@pytest.mark.parametrize("currency", ["USD", "EUR", "AZN", "SGD"])
def test_explicit_extracted_currency_is_preserved_without_symbol(currency, gemini):
    _, enqueue = gemini
    parameters = {"query": "headphones", "currency": currency,
                  "max_price_azn" if currency == "AZN" else "max_price": 100}
    enqueue(route("shopping", "shopping", parameters))
    p = GeminiRouter(Settings(api_key="test")).route("Show headphones under 100", SessionState()).intents[0].parameters
    assert p.currency == currency
    assert (p.max_price_azn if currency == "AZN" else p.max_price) == 100


def test_explicit_iso_currency_takes_precedence_over_symbol_and_model_default(gemini):
    _, enqueue = gemini
    enqueue(route("shopping", "shopping", {"query": "headphones", "currency": "AZN", "max_price_azn": 100}))
    p = GeminiRouter(Settings(api_key="test")).route(
        "Show headphones under $100 SGD", SessionState()).intents[0].parameters
    assert p.currency == "SGD" and p.max_price == 100 and p.max_price_azn is None


def test_no_currency_keeps_existing_local_budget_behavior():
    router = LocalRouter(Repositories.empty())
    p = router.route("Show headphones under 100", SessionState()).intents[0].parameters
    assert p.currency is None and p.max_price_azn == 100 and p.max_price is None
    p = router.route("Show headphones", SessionState()).intents[0].parameters
    assert p.currency is None and p.max_price_azn is None and p.max_price is None


@pytest.mark.parametrize("routing_mode", ["offline", "strict"])
def test_symbol_follow_up_clears_prior_azn_bounds(routing_mode, gemini):
    state = SessionState(last_active_domain=Domain.SHOPPING)
    state.shopping.intent = "search"
    state.shopping.parameters = ShoppingParameters(query="headphones", currency="AZN", min_price_azn=10, max_price_azn=200)
    if routing_mode == "offline":
        router = LocalRouter(Repositories.empty())
    else:
        _, enqueue = gemini
        enqueue(route("follow_up", "shopping", {"currency": "AZN", "max_price_azn": 100}, intent="filter"))
        router = GeminiRouter(Settings(api_key="test"))
    apply_routing(state, router.route("under $100", state))
    p = state.shopping.parameters
    assert p.query == "headphones"
    assert p.currency == "USD" and p.max_price == 100
    assert p.min_price_azn is None and p.max_price_azn is None


@pytest.mark.parametrize("routing_mode", ["offline", "strict"])
def test_dollar_budget_reaches_buywhere_as_usd(routing_mode, gemini):
    if routing_mode == "strict":
        _, enqueue = gemini
        enqueue(route("shopping", "shopping", {"query": "headphones", "currency": "AZN", "max_price_azn": 100}))
    app = create_app(Settings(api_key="test", routing_mode=routing_mode))
    requests = []
    def handler(request):
        requests.append(request)
        assert request.url.params["q"] == "wireless headphones"
        assert request.url.params["currency"] == "USD" and request.url.params["max_price"] == "100.0"
        return httpx.Response(200, json={"data": [{"id": "123", "title": "Wireless headphones",
            "price": {"amount": 49.99, "currency": "USD"}, "url": "https://retailer.example/products/123"}]})
    with TestClient(app) as client:
        app.state.chat_service.engine.http.transport = httpx.MockTransport(handler)
        body = client.post("/api/chat", json={"message": "Show me wireless headphones under $100"}).json()
    assert len(requests) == 1 and body["results"][0]["status"] == "ok"
    p = body["state"]["shopping"]["parameters"]
    assert p["currency"] == "USD" and p["max_price"] == 100 and p.get("max_price_azn") is None


def test_local_mixed_request_keeps_currencies_in_their_domains():
    result = LocalRouter(Repositories.empty()).route(
        "Flights to Istanbul under 500 AZN and wireless headphones under $100", SessionState())
    flight, shopping = result.intents
    assert flight.parameters.currency == "AZN" and flight.parameters.max_price_azn == 500
    assert shopping.parameters.currency == "USD" and shopping.parameters.max_price == 100
    assert shopping.parameters.max_price_azn is None
