"""Live-test regressions through actual routers and provider adapters, with offline HTTP."""

from datetime import date
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from conftest import route


@pytest.fixture(params=["gemini", "local", "fallback"])
def routed_client(request, gemini, monkeypatch):
    generate, enqueue = gemini
    monkeypatch.setattr(Settings, "reference_date", lambda self: date(2026, 11, 3))
    mode = request.param
    if mode == "fallback":
        enqueue(RuntimeError("simulated Gemini outage"))
    app = create_app(Settings(api_key="test", routing_mode="offline" if mode == "local" else "auto",
                              travelpayouts_token="test", provider_retries=0))
    calls = []

    def handler(req):
        calls.append(req)
        if req.url.host == "autocomplete.travelpayouts.com":
            city = req.url.params["term"].casefold()
            return httpx.Response(200, json=[{"type": "city", "code": "GYD" if city == "baku" else "IST", "name": city}])
        if req.url.host == "api.travelpayouts.com":
            day = req.url.params["departure_at"]
            return httpx.Response(200, json={"success": True, "currency": req.url.params["currency"], "data": [{
                "origin": "GYD", "destination": "IST", "departure_at": day + "T10:00:00+04:00",
                "price": 120, "airline": "J2", "flight_number": "75", "transfers": 0}]})
        assert req.url.host == "api.buywhere.ai" and req.url.path == "/v1/products/search"
        noun = "Laptop" if "laptop" in req.url.params["q"].casefold() else "Headphones"
        return httpx.Response(200, json={"data": [{"id": noun.lower() + str(i), "title": noun + " " + str(i),
            "price": {"amount": amount, "currency": "USD"},
            "url": "https://retailer.example/products/" + str(i)} for i, amount in enumerate(["49.99", "100", "100.01", "599"])]})

    with TestClient(app) as client:
        app.state.chat_service.engine.http.transport = httpx.MockTransport(handler)

        def send(message, payload, sid=None):
            if mode == "gemini":
                enqueue(payload)
            response = client.post("/api/chat", json={"message": message, **({"session_id": sid} if sid else {})})
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["routing"]["source"] == ("gemini" if mode == "gemini" else "local")
            return body

        yield send, app, calls, mode
        if mode == "local":
            generate.assert_not_called()
        elif mode == "fallback":
            assert generate.call_count == 1
            assert client.get("/api/client").json()["routing_status"] == "cooldown"


@pytest.mark.parametrize("expression,expected", [("Friday", "2026-11-06"), ("2026-12-01", "2026-12-01"),
                                                 ("12 November", "2026-11-12")])
def test_mixed_flight_shopping_keeps_departure_and_usd_budget(routed_client, expression, expected):
    send, app, calls, mode = routed_client
    payload = {"category": "mixed", "domains": ["flights", "shopping"], "intents": [
        {"domain": "flights", "intent": "search", "parameters": {"origin": "Baku", "destination": "Istanbul"}},
        {"domain": "shopping", "intent": "search", "parameters": {"query": "headphones", "currency": "AZN"}}]}
    body = send(f"Find flights from Baku to Istanbul on {expression} and wireless headphones under 100 USD", payload)
    assert body["state"]["flights"]["parameters"]["departure_date"] == expected
    assert body["state"]["shopping"]["parameters"]["query"] == "wireless headphones"
    assert body["state"]["shopping"]["parameters"]["max_price"] == 100
    assert all(r["status"] == "ok" for r in body["results"])
    flight_req = next(r for r in calls if r.url.host == "api.travelpayouts.com")
    assert flight_req.url.params["departure_at"] == expected and flight_req.url.params["currency"] == "azn"
    shop_req = next(r for r in calls if r.url.host == "api.buywhere.ai")
    assert shop_req.url.params["max_price"] == "100.0" and shop_req.url.params["currency"] == "USD"
    assert [p["price"]["amount"] for p in body["results"][1]["data"]["products"]] == ["49.99", "100"]


def test_new_laptop_search_cannot_resume_headphone_selection_or_filters(routed_client):
    send, app, calls, mode = routed_client
    first = send("Show me wireless headphones under 100 USD",
                 route("shopping", "shopping", {"query": "wireless headphones", "currency": "USD", "max_price": 100}))
    sid = first["session_id"]
    send("Show details for the first product", route("follow_up", "shopping", {"result_positions": [1]}, intent="details"), sid)
    from uuid import UUID
    with app.state.sessions.transaction(UUID(sid)) as state:
        state.flights.parameters.origin = "GYD"
        state.cinema.parameters.movie_title = "Saved CinemaPlus movie"
        state.shopping.parameters.brand = "Old headphone brand"
        state.shopping.parameters.category = "Headphones"
        state.shopping.parameters.color = "black"
        state.shopping.parameters.in_stock = True
        state.shopping.parameters.sort_by = "price_desc"
    body = send("Show me laptops", route("follow_up", "shopping", {
        "query": "wireless headphones", "category": "Headphones", "brand": "Old headphone brand",
        "color": "black", "in_stock": True, "currency": "USD", "max_price": 100,
        "product_ids": ["BW-headphones0"]}, intent="resume"), sid)
    assert body["results"][0]["status"] == "ok"
    assert body["routing"]["intents"][0]["intent"] == "search" and body["routing"]["intents"][0]["reset_context"]
    assert body["state"]["shopping"]["parameters"] == {"query": "laptops"}
    assert all(p["title"].startswith("Laptop") for p in body["results"][0]["data"]["products"])
    assert body["state"]["shopping"]["selected_ids"] == []
    assert body["state"]["flights"]["parameters"] == {"origin": "GYD"}
    assert body["state"]["cinema"]["parameters"] == {"movie_title": "Saved CinemaPlus movie"}
    assert body["state"]["shopping"]["last_result_ids"] == ["BW-laptop" + str(i) for i in range(4)]
    request = [r for r in calls if r.url.host == "api.buywhere.ai"][-1]
    assert request.url.params["q"] == "laptops" and "max_price" not in request.url.params


@pytest.mark.parametrize("budget", ["under 100 USD", "with a budget of 100 USD", "with a 100 USD budget"])
def test_100_usd_budget_excludes_upstream_over_budget_rows(routed_client, budget):
    send, app, calls, mode = routed_client
    body = send("Show me wireless headphones " + budget,
                route("shopping", "shopping", {"query": "headphones", "currency": "USD"}))
    result = body["results"][0]
    assert result["status"] == "ok" and result["data"]["products"]
    assert len(result["data"]["products"]) == 2
    assert all(Decimal(p["price"]["amount"]) <= 100 and p["price"]["currency"] == "USD" for p in result["data"]["products"])
    assert calls[-1].url.params["q"] == "wireless headphones" and calls[-1].url.params["max_price"] == "100.0"


def test_genuine_budget_sort_details_followups_keep_query_and_context(routed_client):
    send, app, calls, mode = routed_client
    first = send("Show me laptops", route("shopping", "shopping", {"query": "laptops"}))
    sid = first["session_id"]
    payload = route("follow_up", "shopping", {"currency": "USD", "max_price": 100}, intent="filter")
    payload["intents"][0]["reset_context"] = True  # A model reset must not erase the referent.
    budget = send("Under 100 USD", payload, sid)
    assert budget["state"]["shopping"]["parameters"]["query"] == "laptops"
    sorted_ = send("Cheapest first", route("follow_up", "shopping", {"sort_by": "price_asc"}, intent="sort"), sid)
    assert sorted_["state"]["shopping"]["parameters"] == {"query": "laptops", "currency": "USD", "max_price": 100, "sort_by": "price_asc"}
    before_calls = len(calls)
    details = send("Show details for the first product", route("follow_up", "shopping", {"result_positions": [1]}, intent="details"), sid)
    assert details["results"][0]["data"]["products"][0]["id"] == "BW-laptop0"
    assert len(calls) == before_calls
    assert details["state"]["shopping"]["parameters"]["max_price"] == 100
    tighter = send("Under 50", route("follow_up", "shopping", {"max_price_azn": 50}, intent="filter"), sid)
    assert tighter["state"]["shopping"]["parameters"]["currency"] == "USD"
    assert tighter["state"]["shopping"]["parameters"]["max_price"] == 50
    assert tighter["state"]["shopping"]["parameters"]["query"] == "laptops"
    assert len(tighter["results"][0]["data"]["products"]) == 1
