import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from test_frontend_integration import post


@pytest.mark.parametrize("message", ["Show me iPhone", "iPhone", "Find iPhone under 1500 AZN", "Show products named Galaxy phone"])
def test_specific_missing_product_does_not_broaden(message):
    with TestClient(create_app(Settings(data_mode="fixtures", routing_mode="offline"))) as client:
        answer = post(client, message)
        assert answer["results"][0]["status"] == "no_results"
        assert answer["results"][0]["data"]["products"] == []
        assert answer["message"] == "No matching products found."


def test_all_products_clears_previous_search_and_preserves_cart():
    with TestClient(create_app(Settings(data_mode="fixtures", routing_mode="offline"))) as client:
        first = post(client, "Add 1 P001 to my cart")
        sid = first["session_id"]
        post(client, "Show iPhone under 100 AZN", sid)
        answer = post(client, "Show all products", sid)
        assert len(answer["results"][0]["data"]["products"]) == 12
        assert answer["state"]["shopping"]["cart"] == {"P001": 1}


def test_gemini_cannot_broaden_explicit_product_name(client, gemini):
    _, enqueue = gemini
    enqueue({"category": "shopping", "domains": ["shopping"], "intents": [
        {"domain": "shopping", "intent": "search", "parameters": {"query": "phone"}}]})
    answer = post(client, "Show me iPhone")
    assert answer["results"][0]["data"]["products"] == []
    assert answer["message"] == "No matching products found."


def test_laptop_search_never_substitutes_backpack_when_budget_excludes_laptops():
    with TestClient(create_app(Settings(data_mode="fixtures", routing_mode="offline"))) as client:
        answer = post(client, "Show laptop under 100 AZN")
        assert answer["results"][0]["data"]["products"] == []


def test_phone_search_excludes_headphones():
    with TestClient(create_app(Settings(data_mode="fixtures", routing_mode="offline"))) as client:
        answer = post(client, "Show phones")
        assert {row["id"] for row in answer["results"][0]["data"]["products"]} == {"P005", "P006"}
