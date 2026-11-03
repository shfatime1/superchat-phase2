import json
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.domain_models import DomainResult
from app.main import create_app
from app.responses import GeminiResponseFormulator, ResponsePlan, ResponseSection
from conftest import route
from test_chat import send

REAL_GENERATE_PLAN = GeminiResponseFormulator.generate_plan


def test_natural_language_search_selection_cart_and_return(client, gemini):
    _, enqueue = gemini
    enqueue(route("shopping", "shopping", {"query": "laptops", "sort_by": "price_asc"}),
            route("follow_up", "shopping", {"result_positions": [1], "quantity": 2}, intent="cart_add"),
            route("cinema", "cinema", {"date_text": "tonight"}),
            route("flights", "flights", {"origin": "Baku", "destination": "Istanbul", "departure_date_text": "Friday"}),
            route("follow_up", "shopping", intent="cart_view"))
    first = send(client, "Show me laptops cheapest first")
    sid = first["session_id"]
    assert [row["id"] for row in first["results"][0]["data"]["products"]] == ["P004", "P003"]
    added = send(client, "Add two of the first one", sid)
    assert added["results"][0]["data"]["cart"]["total_azn"] == "2498.00"
    send(client, "What is playing tonight?", sid)
    flights = send(client, "Flights from Baku to Istanbul on Friday", sid)
    assert len(flights["results"][0]["data"]["flights"]) == 3
    final = send(client, "Back to my cart", sid)
    assert final["state"]["shopping"]["cart"] == {"P004": 2}
    assert "2498.00 AZN" in final["message"]
    assert final["state"]["cinema"]["parameters"]["date"] == "2026-11-02"
    assert final["state"]["flights"]["parameters"]["departure_date"] == "2026-11-06"


def test_flight_booking_quantity_followup_and_global_capacity(client, gemini):
    _, enqueue = gemini
    enqueue(route("flights", "flights", {"flight_ids": ["F002"]}, intent="reserve"),
            route("follow_up", "flights", {"passengers": 2}, intent="follow_up"),
            route("flights", "flights", {"flight_ids": ["F002"], "passengers": 2}, intent="reserve"))
    first = send(client, "Reserve flight F002")
    assert first["results"][0]["status"] == "clarification"
    completed = send(client, "Two passengers", first["session_id"])
    confirmation = completed["results"][0]["data"]["reservation"]["confirmation_id"]
    assert confirmation.startswith("MOCK-")
    assert confirmation in completed["message"]
    assert "no payment or real-world booking" in completed["message"]
    denied = send(client, "Reserve F002 for two passengers")
    assert denied["results"][0]["code"] == "insufficient_seats"
    assert denied["state"]["flights"]["reservations"] == []
    assert confirmation not in json.dumps(denied)


def test_cinema_date_return_and_ordinal_showtime_reservation(client, gemini):
    _, enqueue = gemini
    enqueue(route("cinema", "cinema", {"genre": "sci-fi", "date_text": "tonight"}),
            route("shopping", "shopping", {"query": "headphones"}),
            route("follow_up", "cinema", {"date_text": "Saturday", "reference": "the sci-fi one"}, intent="availability"),
            route("follow_up", "cinema", {"result_positions": [1], "tickets": 2}, intent="reserve"))
    first = send(client, "What sci-fi is playing tonight?")
    sid = first["session_id"]
    send(client, "Headphones please", sid)
    returned = send(client, "Back to sci-fi, any seats on Saturday?", sid)
    assert [row["id"] for row in returned["results"][0]["data"]["showtimes"]] == ["S011", "S012"]
    booked = send(client, "Two tickets for the first showtime", sid)
    assert booked["results"][0]["data"]["reservation"]["record_id"] == "S011"
    assert booked["results"][0]["data"]["reservation"]["total_azn"] == "22.00"


def test_mixed_executes_all_and_reports_partial_business_failure(client, gemini):
    _, enqueue = gemini
    enqueue({"category": "mixed", "domains": ["shopping", "cinema", "flights"], "intents": [
        {"domain": "shopping", "intent": "cart_add", "parameters": {"product_ids": ["P001"], "quantity": 1}},
        {"domain": "cinema", "intent": "reserve", "parameters": {"showtime_ids": ["S003"], "tickets": 1}},
        {"domain": "flights", "intent": "details", "parameters": {"flight_ids": ["F001"]}},
    ]})
    answer = send(client, "Add one P001, book one S003 ticket, and show F001 details")
    assert [result["status"] for result in answer["results"]] == ["ok", "error", "ok"]
    assert answer["state"]["shopping"]["cart"] == {"P001": 1}
    assert answer["state"]["cinema"]["reservations"] == []
    for label in ("Shopping", "Cinema", "Flights"):
        assert label in answer["message"]


@pytest.mark.parametrize("language,message,expected", [
    ("en", "Show me headphones", "Wireless Headphones"),
    ("az", "Mənə simsiz qulaqlıq göstər", "Simsiz qulaqlıq"),
    ("ru", "Покажи беспроводные наушники", "Беспроводные наушники"),
])
def test_user_language_grounded_response(client, gemini, language, message, expected):
    _, enqueue = gemini
    enqueue(route("shopping", "shopping", {"query": "headphones"}, language=language))
    answer = send(client, message)
    assert expected in answer["message"]
    assert "89.90 AZN" in answer["message"]


def test_unknown_record_never_produces_confirmation(client, gemini):
    _, enqueue = gemini
    enqueue(route("flights", "flights", {"flight_ids": ["F999"], "passengers": 1}, intent="reserve"))
    answer = send(client, "Reserve F999 for one")
    assert answer["results"][0]["code"] == "unknown_id"
    assert answer["state"]["flights"]["reservations"] == []
    assert "MOCK-" not in answer["message"]


@pytest.mark.parametrize("quantity", [0, -1, 1.5])
def test_invalid_quantity_does_not_mutate_existing_session(client, gemini, quantity):
    _, enqueue = gemini
    enqueue(route("shopping", "shopping", {"query": "headphones"}),
            route("follow_up", "shopping", {"product_ids": ["P001"], "quantity": quantity}, intent="cart_add"))
    first = send(client, "Headphones please")
    sid = first["session_id"]
    response = client.post("/api/chat", json={"message": "Add an invalid quantity", "session_id": sid})
    assert response.status_code == 502
    assert client.get(f"/api/session/{sid}").json() == first["state"]


def test_formulation_failure_still_returns_committed_mock_booking(client, gemini, monkeypatch):
    _, enqueue = gemini
    enqueue(route("flights", "flights", {"flight_ids": ["F002"], "passengers": 1}, intent="reserve"))
    def broken(*args):
        raise RuntimeError("provider-secret")
    monkeypatch.setattr(GeminiResponseFormulator, "generate_plan", broken)
    answer = send(client, "Reserve F002 for one")
    assert answer["results"][0]["code"] == "reserved"
    assert "provider-secret" not in answer["message"]
    assert len(client.get(f"/api/session/{answer['session_id']}").json()["flights"]["reservations"]) == 1


def test_actual_response_sdk_adapter_uses_schema_and_grounded_results(gemini, monkeypatch):
    generate, _ = gemini
    generate.side_effect = None
    generate.return_value = MagicMock(text='{"sections":[{"result_index":0,"phrasing":"helpful"}]}')
    monkeypatch.setattr(GeminiResponseFormulator, "generate_plan", REAL_GENERATE_PLAN)
    formulator = GeminiResponseFormulator(Settings(data_mode="fixtures", api_key="test"))
    outcome = DomainResult(domain="shopping", operation="search", status="no_results", code="no_results")
    answer = formulator.formulate("Find a spaceship", "en", [outcome], "shopping")
    sent = json.loads(generate.call_args.kwargs["contents"])
    assert sent["results"] == [outcome.model_dump(mode="json")]
    assert generate.call_args.kwargs["config"].response_mime_type == "application/json"
    assert "No matching products" in answer


@pytest.mark.parametrize("text", [
    '{"sections":[],"confirmation":"FAKE-123","price":1}',
    '{"sections":[{"result_index":9,"phrasing":"direct"}]}',
    '{"sections":[]}',
    'The booking is paid and confirmed: FAKE-123',
])
def test_response_model_cannot_invent_facts_or_omit_results(gemini, monkeypatch, text):
    generate, _ = gemini
    generate.side_effect = None
    generate.return_value = MagicMock(text=text)
    monkeypatch.setattr(GeminiResponseFormulator, "generate_plan", REAL_GENERATE_PLAN)
    outcome = DomainResult(domain="cinema", operation="reserve", status="error", code="insufficient_seats")
    answer = GeminiResponseFormulator(Settings(data_mode="fixtures", api_key="test")).formulate("Book it", "en", [outcome], "cinema")
    assert "not enough seats" in answer
    assert "FAKE" not in answer
    assert "paid" not in answer


def test_unexpected_failure_rolls_back_both_inventory_and_session(client, gemini, monkeypatch):
    _, enqueue = gemini
    enqueue(route("flights", "flights", {"flight_ids": ["F002"]}, intent="details"),
            route("follow_up", "flights", {"flight_ids": ["F002"], "passengers": 2}, intent="reserve"))
    first = send(client, "Show F002")
    service = client.app.state.chat_service
    def broken(*args, **kwargs):
        raise RuntimeError("unexpected programming error")
    monkeypatch.setattr(service.formulator, "formulate", broken)
    with pytest.raises(RuntimeError):
        client.post("/api/chat", json={"message": "Book two", "session_id": first["session_id"]})
    assert client.get(f"/api/session/{first['session_id']}").json() == first["state"]
    row = service.engine.services["flights"].repo.get_by_id("F002")
    assert service.engine.inventory.available(row) == 3


def test_chat_calls_gemini_for_routing_then_response_plan(client, gemini, monkeypatch):
    generate, enqueue = gemini
    monkeypatch.setattr(GeminiResponseFormulator, "generate_plan", REAL_GENERATE_PLAN)
    enqueue(route("shopping", "shopping", {"query": "headphones"}),
            {"sections": [{"result_index": 0, "phrasing": "helpful"}]})
    answer = send(client, "Show me headphones")
    assert generate.call_count == 2
    assert "matching options" in answer["message"]
    sent = json.loads(generate.call_args.kwargs["contents"])
    assert sent["results"][0]["data"]["products"][0]["price_azn"] == 89.9
