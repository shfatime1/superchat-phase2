"""Real eBay API contract shapes with synthetic responses and no live credentials."""

import asyncio
import base64
from urllib.parse import parse_qs

import httpx
import pytest

from app.config import Settings
from app.providers.ebay import EbayProvider
from app.providers.engine import ProviderDomainEngine
from app.providers.http import ProviderHTTP
from app.schemas import ShoppingParameters, RoutingResult
from app.state import SessionState

ITEM = {"itemId": "v1|123|0", "title": "Wireless headphones", "price": {"value": "49.99", "currency": "USD"},
        "image": {"imageUrl": "https://i.ebayimg.com/images/example.jpg"}, "itemWebUrl": "https://www.ebay.com/itm/123",
        "categories": [{"categoryId": "112529", "categoryName": "Headphones"}], "condition": "New"}


def run(coro):
    return asyncio.run(coro)


def http(handler, clock=None):
    return ProviderHTTP(transport=httpx.MockTransport(handler), retries=0, clock=clock or (lambda: 0))


def test_client_credentials_are_reused_and_renewed_without_exposure():
    requests, tick = [], [0]
    def handler(request):
        requests.append(request)
        if request.url.path.endswith("/oauth2/token"):
            assert request.method == "POST"
            assert request.headers["Authorization"] == "Basic " + base64.b64encode(b"client:secret").decode()
            assert parse_qs(request.content.decode())["grant_type"] == ["client_credentials"]
            return httpx.Response(200, json={"access_token": "managed-secret", "expires_in": 100})
        assert request.headers["Authorization"] == "Bearer managed-secret"
        return httpx.Response(200, json={"total": 1, "itemSummaries": [ITEM]})
    provider = EbayProvider(http(handler, lambda: tick[0]), client_id="client", client_secret="secret")
    first = run(provider.search(ShoppingParameters(query="headphones")))
    second = run(provider.search(ShoppingParameters(query="headphones")))
    assert first.items[0].category == "Headphones" and first.items[0].image_url.startswith("https://i.ebayimg.com/")
    assert second.source.status == "cached" and len(requests) == 2
    tick[0] = 95
    renewed = run(provider.search(ShoppingParameters(query="headphones")))
    assert sum(r.url.path.endswith("/oauth2/token") for r in requests) == 2
    assert "managed-secret" not in renewed.model_dump_json()
    settings = Settings(ebay_client_id="private-id", ebay_client_secret="private-secret")
    assert "private" not in repr(settings)


def test_live_item_details_supply_only_reported_brand_stock_and_text():
    def handler(request):
        assert request.url.path.endswith("/item/v1|123|0")
        return httpx.Response(200, json={**ITEM, "localizedAspects": [{"name": "Brand", "value": "Sony"}, {"name": "Color", "value": "Black"}],
            "estimatedAvailabilities": [{"estimatedAvailabilityStatus": "IN_STOCK"}],
            "shortDescription": "<b>Wireless</b> headphones"})
    result = run(EbayProvider(http(handler), "test").details("EBAY-v1|123|0"))
    row = result.items[0]
    assert row.brand == "Sony" and row.color == "Black" and row.in_stock is True
    assert row.description == "Wireless headphones" and row.availability_status == "IN_STOCK"
    assert result.source.provider == "eBay"
    assert EbayProvider.normalize(ITEM).in_stock is None


def test_category_brand_color_filters_use_documented_refinements():
    requests = []
    def handler(request):
        requests.append(request)
        if "fieldgroups" in request.url.params:
            return httpx.Response(200, json={"total": 1, "refinement": {"dominantCategoryId": "112529",
                "categoryDistributions": [{"categoryId": "112529", "categoryName": "Headphones"}],
                "aspectDistributions": [{"localizedAspectName": "Brand"}, {"localizedAspectName": "Color"}]}})
        assert request.url.params["category_ids"] == "112529"
        assert request.url.params["aspect_filter"] == "categoryId:112529,Brand:{Sony},Color:{Black}"
        return httpx.Response(200, json={"total": 1, "itemSummaries": [ITEM]})
    result = run(EbayProvider(http(handler), "test").search(ShoppingParameters(query="headphones", category="Headphones", brand="Sony", color="Black")))
    assert len(result.items) == 1 and len(requests) == 2


@pytest.mark.parametrize("status,code", [(401, "credentials_or_permissions"), (429, "rate_limited"), (503, "upstream_error")])
def test_auth_errors_are_safe_and_do_not_fabricate_products(status, code):
    result = run(EbayProvider(http(lambda r: httpx.Response(status, text="secret", headers={"Retry-After": "5"})),
        client_id="client", client_secret="secret").search(ShoppingParameters(query="headphones")))
    assert result.error.code == code and not result.items and "secret" not in result.model_dump_json()


def test_search_and_details_share_conversation_selection_and_refresh_details():
    def handler(request):
        return httpx.Response(200, json={**ITEM, "localizedAspects": [{"name": "Brand", "value": "Sony"}]}
            if "/item/" in request.url.path else {"total": 1, "itemSummaries": [ITEM]})
    engine = ProviderDomainEngine(Settings(ebay_token="test"), http(handler))
    state = SessionState()
    def route(action, **p):
        return RoutingResult.model_validate({"category": "shopping", "domains": ["shopping"], "intents": [{"domain": "shopping", "intent": action, "parameters": p}]})
    first = engine.execute(route("search", query="headphones"), state)[0]
    assert first.data["provider"]["provider"] == "eBay"
    second = engine.execute(route("details", result_positions=[1]), state)[0]
    assert second.data["products"][0]["brand"] == "Sony"
    assert state.shopping.selected_ids == ["EBAY-v1|123|0"]


def test_missing_configuration_tells_render_setup_and_never_uses_fixtures():
    provider = EbayProvider(http(lambda r: pytest.fail("HTTP without credentials")))
    result = run(provider.search(ShoppingParameters(query="phone")))
    assert result.error.code == "missing_credentials" and "EBAY_CLIENT_ID" in result.source.notice
    assert result.items == []


def test_native_currency_budget_uses_provider_filter_and_checks_response():
    def handler(request):
        assert request.url.params["filter"] == "price:[20.0..50.0],priceCurrency:USD"
        return httpx.Response(200, json={"total": 1, "itemSummaries": [ITEM]})
    provider = EbayProvider(http(handler), "test")
    result = run(provider.search(ShoppingParameters(query="headphones", currency="USD", min_price=20, max_price=50)))
    assert result.error is None and len(result.items) == 1
    assert run(provider.search(ShoppingParameters(query="headphones", max_price=50))).error.code == "currency_required"


def test_ignored_filter_warning_is_reported_instead_of_claiming_filtered_results():
    provider = EbayProvider(http(lambda r: httpx.Response(200, json={"total": 1, "itemSummaries": [ITEM],
        "warnings": [{"errorId": 12012, "message": "price filter ignored"}]})), "test")
    result = run(provider.search(ShoppingParameters(query="headphones", currency="USD", max_price=50)))
    assert result.error.code == "unsupported_filter" and not result.items


def test_local_currency_budget_is_not_mislabeled_azn():
    from app.fallback import LocalRouter
    from app.repositories import Repositories
    result = LocalRouter(Repositories.empty()).route("Show headphones under 50 USD", SessionState())
    p = result.intents[0].parameters
    assert p.currency == "USD" and p.max_price == 50 and p.max_price_azn is None
