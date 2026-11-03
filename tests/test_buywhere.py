"""Public API contracts and Shopping regressions; all automated HTTP is offline."""

import asyncio
from datetime import datetime, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.providers.buywhere import BuyWhereProvider, API, public_https
from app.providers.engine import ProviderDomainEngine
from app.providers.http import ProviderHTTP
from app.schemas import ShoppingParameters, RoutingResult
from app.state import SessionState

ITEM = {"id": "8242752712", "title": "Bluetooth headphones", "price": {"amount": "13.99", "currency": "USD"},
        "merchant": "amazon_us", "url": "https://www.amazon.com/dp/B0H3P59RQZ",
        "image_url": "https://m.media-amazon.com/images/I/71FSiyK+FCL.jpg", "availability": "local",
        "category_path": ["Electronics", "Headphones"], "country_code": "US",
        "price_as_of": "2026-01-01T00:00:00Z",
        "affiliate_redirect_url": "https://buywhere.ai/r/direct/8242752712?source=product_card"}


def run(coro):
    return asyncio.run(coro)


def http(handler, **kwargs):
    return ProviderHTTP(transport=httpx.MockTransport(handler), retries=0, **kwargs)


def route(operation="search", **parameters):
    return RoutingResult.model_validate({"category": "shopping", "domains": ["shopping"], "intents": [
        {"domain": "shopping", "intent": operation, "parameters": parameters}]})


def test_public_search_real_contract_images_links_native_prices_and_cache():
    calls = []
    def handler(request):
        calls.append(request)
        assert str(request.url).startswith(API + "/products/search?")
        assert "Authorization" not in request.headers
        assert request.url.params["q"] == "headphones"
        assert request.url.params["country_code"] == request.url.params["deliver_to"] == "US"
        assert request.url.params["include_unshippable"] == "false"
        return httpx.Response(200, json={"data": [ITEM], "meta": {"has_more": True, "cached": False}})
    provider = BuyWhereProvider(http(handler))
    first = run(provider.search(ShoppingParameters(query="headphones")))
    assert first.error is None and first.source.status == "live"
    row = first.items[0]
    assert row.id == "BW-8242752712" and str(row.price.amount) == "13.99"
    assert row.price.currency == "USD" and row.image_url == ITEM["image_url"]
    assert row.product_url == ITEM["affiliate_redirect_url"] and row.merchant == "amazon_us"
    assert row.category == "Electronics / Headphones" and row.in_stock is None
    assert row.price_as_of == datetime(2026, 1, 1, tzinfo=timezone.utc) and row.price_stale is True
    assert first.partial and "commission" in first.source.notice and "Azerbaijan" in first.source.notice
    cached = run(provider.search(ShoppingParameters(query="headphones")))
    assert cached.source.status == "cached" and cached.source.local_cache_hit
    assert cached.source.fetched_at == first.source.fetched_at and len(calls) == 1


@pytest.mark.parametrize("availability", ["local", "unavailable", "unknown", None])
def test_delivery_ranking_is_never_mistaken_for_stock(availability):
    row = BuyWhereProvider.normalize({**ITEM, "availability": availability, "price_as_of": None,
                                      "updated_at": "2026-11-03T00:00:00Z"})
    assert row.in_stock is None and row.availability_status is None
    assert row.price_as_of is None and row.price_stale is None


def test_native_budgets_sorting_and_currency_checks_when_upstream_ignores_filters():
    def handler(request):
        assert request.url.params["currency"] == "USD"
        assert request.url.params["min_price"] == "13.99" and request.url.params["max_price"] == "20.0"
        return httpx.Response(200, json={"data": [ITEM,
            {**ITEM, "id": "2", "price": {"amount": "19.99", "currency": "USD"}},
            {**ITEM, "id": "3", "price": {"amount": "200", "currency": "USD"}},
            {**ITEM, "id": "4", "price": {"amount": "14", "currency": "SGD"}}]})
    result = run(BuyWhereProvider(http(handler)).search(ShoppingParameters(query="headphones", currency="USD",
        min_price=13.99, max_price=20, sort_by="price_desc")))
    assert result.error is None
    assert [str(row.price.amount) for row in result.items] == ["19.99", "13.99"]


@pytest.mark.parametrize("parameters,code", [
    ({}, "query_required"), ({"color": "black"}, "unsupported_filter"),
    ({"in_stock": True}, "unsupported_filter"), ({"max_price_azn": 100}, "currency_filter_mismatch"),
    ({"max_price": 100}, "currency_required"), ({"currency": "EUR"}, "currency_filter_mismatch"),
    ({"currency": "USD", "min_price": 20, "max_price": 10}, "invalid_range"),
    ({"sort_by": "rating_asc"}, "invalid_sort"),
])
def test_unsupported_constraints_fail_before_http(parameters, code):
    p = ShoppingParameters(**({"query": "headphones", **parameters} if parameters else {}))
    result = run(BuyWhereProvider(http(lambda r: pytest.fail("HTTP for invalid constraints"))).search(p))
    assert result.error.code == code and result.items == []


def test_category_and_reported_brand_filters_apply_to_returned_subset():
    provider = BuyWhereProvider(http(lambda r: httpx.Response(200, json={"data": [
        {**ITEM, "brand": "Sony"}, {**ITEM, "id": "2", "brand": "Other"}]})))
    result = run(provider.search(ShoppingParameters(query="headphones", category="Electronics", brand="Sony")))
    assert len(result.items) == 1 and result.items[0].brand == "Sony" and result.partial


@pytest.mark.parametrize("status,code", [(403, "credentials_or_permissions"), (429, "rate_limited"), (503, "upstream_error")])
def test_upstream_failures_return_no_fabricated_products(status, code):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status, text="sensitive provider text", headers={"Retry-After": "42"})
    provider = BuyWhereProvider(http(handler))
    result = run(provider.search(ShoppingParameters(query="laptop")))
    assert result.error.code == code and not result.items and "sensitive" not in result.model_dump_json()
    if status == 429:
        assert result.error.retry_after == 42
        run(provider.search(ShoppingParameters(query="laptop")))
        assert len(calls) == 1


@pytest.mark.parametrize("payload,code", [
    ({"data": []}, None), ({"data": [] , "meta": {"degraded": True}}, "upstream_degraded"),
    ({"data": [], "meta": {"emptiness_reason": "timeout"}}, "upstream_degraded"),
    ({"data": {}}, "invalid_response"), ({"data": [{**ITEM, "price": {"amount": -1, "currency": "USD"}}]}, "invalid_response"),
    ({"data": [{**ITEM, "id": "../../private"}]}, "invalid_response"),
    ({"data": [{**ITEM, "price_as_of": "not-a-date"}]}, "invalid_response"),
])
def test_valid_empty_results_are_distinct_from_failed_or_malformed_searches(payload, code):
    result = run(BuyWhereProvider(http(lambda r: httpx.Response(200, json=payload))).search(ShoppingParameters(query="missing")))
    assert (result.error.code if result.error else None) == code and not result.items


@pytest.mark.parametrize("url", ["javascript:alert(1)", "http://shop.example/p", "https://user:pass@shop.example/p",
    "https://127.0.0.1/private", "https://[::1]/private", "https://machine.local/p"])
def test_returned_links_reject_unsafe_protocols_credentials_and_local_hosts(url):
    assert public_https(url) is None


def test_anonymous_details_do_not_call_authenticated_routes():
    result = run(BuyWhereProvider(http(lambda r: pytest.fail("Authenticated URL without key"))).details("BW-8242752712"))
    assert result.error.code == "authorization_required"


def test_optional_key_is_server_side_and_details_validate_identity():
    calls = []
    def handler(request):
        calls.append(request)
        assert request.headers["Authorization"] == "Bearer private-token"
        return httpx.Response(200, json={"data": [ITEM]})
    provider = BuyWhereProvider(http(handler), "private-token")
    result = run(provider.details("BW-8242752712"))
    assert result.error is None and "private-token" not in result.model_dump_json()
    assert run(provider.details("BW-other")).error.code == "invalid_response"
    assert run(provider.details("../x")).error.code == "unknown_id" and len(calls) == 2
    assert "private-token" not in repr(Settings(buywhere_token="private-token"))


def test_default_search_saved_details_comparison_and_no_cart_or_booking_authority():
    calls = []
    def handler(request):
        calls.append(request)
        assert request.url.path == "/v1/products/search"
        return httpx.Response(200, json={"data": [ITEM, {**ITEM, "id": "2", "title": "Second headphones"}]})
    engine, state = ProviderDomainEngine(Settings(), http(handler)), SessionState()
    first = engine.execute(route(query="headphones"), state)[0]
    assert first.status == "ok" and first.data["provider"]["provider"] == "BuyWhere"
    details = engine.execute(route("details", result_positions=[1]), state)[0]
    assert details.status == "ok" and details.data["provider"]["status"] == "cached"
    assert details.data["products"][0]["id"] == "BW-8242752712"
    compared = engine.execute(route("compare", product_ids=state.shopping.last_result_ids), state)[0]
    assert len(compared.data["products"]) == 2 and len(calls) == 1
    blocked = engine.execute(route("cart_add", product_ids=["BW-8242752712"], quantity=1), state)[0]
    assert blocked.code == "unsupported_operation" and blocked.data["provider"]["source_url"] == "https://buywhere.ai/"
    assert state.shopping.cart == {}


def test_api_uses_gemini_routing_and_preserves_history_without_credentials(gemini):
    _, enqueue = gemini
    enqueue(route(query="headphones", currency="USD", max_price=100).model_dump(mode="json"),
            route("details", product_ids=["BW-8242752712"]).model_dump(mode="json"))
    app = create_app(Settings(api_key="test", routing_mode="strict"))
    with TestClient(app) as browser:
        app.state.chat_service.engine.http.transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"data": [ITEM]}))
        first = browser.post("/api/chat", json={"message": "Show headphones under 100 USD"})
        assert first.status_code == 200 and first.json()["results"][0]["status"] == "ok"
        body = first.json()
        assert body["routing"]["source"] == "gemini"
        assert "older than 24 hours" in body["message"] and "2026-01-01" in body["message"]
        second = browser.post("/api/chat", json={"message": "Show details for product BW-8242752712", "session_id": body["session_id"]}).json()
        assert second["results"][0]["status"] == "ok" and len(second["state"]["history"]) == 4
        info = browser.get("/api/providers").json()["shopping"]
        assert info["provider"] == "buywhere" and info["authorized_catalog"] is True and info["api_key_required"] is False


def test_local_router_handles_buywhere_product_buttons_and_native_market_currency():
    from app.fallback import LocalRouter
    from app.repositories import Repositories
    router = LocalRouter(Repositories.empty())
    extracted = router.route("Show details for product BW-8242752712.", SessionState())
    assert extracted.intents[0].parameters.product_ids == ["BW-8242752712"]
    budget = router.route("Show headphones under 100 SGD", SessionState())
    assert budget.intents[0].parameters.currency == "SGD" and budget.intents[0].parameters.max_price == 100
