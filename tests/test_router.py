import json
from datetime import date
from unittest.mock import MagicMock

import pytest

from app.config import Settings
from app.dates import resolve_date
from app.routing import GeminiRouter, InvalidRouterResponse, RouterUnavailable
from app.schemas import Category, Domain
from app.state import SessionState
from conftest import route


@pytest.mark.parametrize("message,payload,category", [
    ("Flights to Istanbul on Friday", route("flights", "flights", {"destination": "Istanbul", "departure_date_text": "Friday"}), "flights"),
    ("Headphones under 100 AZN", route("shopping", "shopping", {"query": "headphones", "max_price_azn": 100}), "shopping"),
    ("What is playing tonight?", route("cinema", "cinema", {"date_text": "tonight"}), "cinema"),
    ("A flight and a backpack", {"category": "mixed", "domains": ["flights", "shopping"], "intents": [
        {"domain": "flights", "intent": "search", "parameters": {}},
        {"domain": "shopping", "intent": "search", "parameters": {"query": "backpack"}}]}, "mixed"),
    ("The cheaper one", route("follow_up", "flights", {"reference": "the cheaper one"}), "follow_up"),
    ("Show me something good", route("ambiguous", clarification="Flights, shopping, or cinema?"), "ambiguous"),
    ("What is the weather in Ganja?", route("out_of_scope"), "out_of_scope"),
])
def test_all_seven_categories_use_structured_gemini(message, payload, category, gemini):
    generate, enqueue = gemini
    enqueue(payload)
    state = SessionState()
    state.flights.intent = "search"
    state.last_active_domain = Domain.FLIGHTS
    result = GeminiRouter(Settings(data_mode="fixtures", api_key="test")).route(message, state)
    assert result.category.value == category
    sent = json.loads(generate.call_args.kwargs["contents"])
    assert sent["message"] == message
    assert sent["reference_date"] == "2026-11-02"
    config = generate.call_args.kwargs["config"]
    assert config.response_mime_type == "application/json"
    assert config.response_json_schema["properties"]["category"]
    assert "Never guess" in config.system_instruction


@pytest.mark.parametrize("expression,expected", [
    ("today", "2026-11-02"), ("tonight", "2026-11-02"),
    ("tomorrow", "2026-11-03"), ("day after tomorrow", "2026-11-04"),
    ("Friday", "2026-11-06"), ("Saturday", "2026-11-07"),
    ("next Friday", "2026-11-13"), ("in 5 days", "2026-11-07"),
    ("2026-11-12", "2026-11-12"), ("sometime", None),
])
def test_reference_date(expression, expected):
    assert resolve_date(expression) == (date.fromisoformat(expected) if expected else None)


def test_relative_date_overrides_wrong_model_clock(gemini):
    _, enqueue = gemini
    enqueue(route("flights", "flights", {"departure_date_text": "Friday", "departure_date": "2030-01-01"}))
    result = GeminiRouter(Settings(data_mode="fixtures", api_key="test")).route("Flights Friday", SessionState())
    assert result.intents[0].parameters.departure_date == date(2026, 11, 6)
    assert result.intents[0].parameters.origin is None


@pytest.mark.parametrize("has_context", [False, True])
def test_contextual_fallback(has_context, gemini):
    _, enqueue = gemini
    enqueue(route("follow_up"))
    state = SessionState()
    if has_context:
        state.last_active_domain = Domain.SHOPPING
        state.shopping.intent = "search"
    result = GeminiRouter(Settings(data_mode="fixtures", api_key="test")).route("the cheaper one", state)
    assert result.category == (Category.FOLLOW_UP if has_context else Category.AMBIGUOUS)
    assert result.domains == ([Domain.SHOPPING] if has_context else [])


def test_follow_up_cannot_invent_missing_prior_context(gemini):
    _, enqueue = gemini
    enqueue(route("follow_up", "cinema", {"tickets": 2}))
    result = GeminiRouter(Settings(data_mode="fixtures", api_key="test")).route("Book two seats", SessionState())
    assert result.category == Category.AMBIGUOUS
    assert result.intents == []


@pytest.mark.parametrize("payload", [
    {"category": "unknown"}, route("flights", "shopping"),
    route("mixed", "flights"), route("out_of_scope", "cinema"),
    route("shopping", "shopping", {"unknown": "invented"}),
    route("flights", "flights", {"passengers": -1}),
    route("shopping", "shopping", {"max_price_azn": float("inf")}),
])
def test_reject_invalid_structured_results(payload, gemini):
    _, enqueue = gemini
    enqueue(payload)
    with pytest.raises(InvalidRouterResponse):
        GeminiRouter(Settings(data_mode="fixtures", api_key="test")).route("hello", SessionState())


@pytest.mark.parametrize("text", [None, "not JSON", "```json\n{}\n```", "{}"])
def test_malformed_output(text, gemini):
    generate, _ = gemini
    generate.side_effect = None
    generate.return_value = MagicMock(text=text)
    with pytest.raises(InvalidRouterResponse):
        GeminiRouter(Settings(data_mode="fixtures", api_key="test")).route("hello", SessionState())


def test_missing_key_and_sanitized_provider_error(gemini):
    generate, enqueue = gemini
    with pytest.raises(RouterUnavailable, match="not configured"):
        GeminiRouter(Settings(data_mode="fixtures", )).route("hello", SessionState())
    generate.assert_not_called()
    enqueue(RuntimeError("secret-provider-key-in-error"))
    with pytest.raises(RouterUnavailable) as exc:
        GeminiRouter(Settings(data_mode="fixtures", api_key="test")).route("hello", SessionState())
    assert "secret" not in str(exc.value)
