"""The eight exact PDF examples, plus critical final regressions. No live calls."""
import asyncio
from datetime import date

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.fallback import LocalRouter
from app.repositories import Repositories
from app.state import SessionState
from app.schemas import ShoppingParameters, CinemaParameters, Domain
from app.providers.http import ProviderHTTP
from app.providers.buywhere import BuyWhereProvider
from app.providers.cinemaplus import CinemaPlusPublicProvider
from app.providers.references import saved_ids
from test_cinemaplus_public import client as public_client, showtime
from test_phase2_ops import ITEM

EXAMPLES = [
    (["Find me a flight from Baku to Istanbul on Friday.", "What is playing tonight?", "Do you have wireless headphones under 100 AZN?"], ["flights", "cinema", "shopping"]),
    (["What is playing tonight?", "Show me laptops.", "Okay, and the sci-fi one, any seats on Saturday?"], ["cinema", "shopping", "follow_up"]),
    (["Show me laptops.", "The second one, is it in stock?"], ["shopping", "follow_up"]),
    (["Flights to Istanbul on 6 November.", "The cheaper one, is it direct?"], ["flights", "follow_up"]),
    (["I need a flight to Istanbul on 6 November and a backpack for the trip."], ["mixed"]),
    (["Show me something good."], ["ambiguous"]),
    (["What is the weather in Ganja?"], ["out_of_scope"]),
    (["Book two seats."], ["ambiguous"]),
]


@pytest.mark.parametrize("messages,categories", EXAMPLES, ids=[f"PDF-{i}" for i in range(1,9)])
def test_pdf_conversation(messages, categories):
    with TestClient(create_app(Settings(data_mode="fixtures", routing_mode="offline"))) as client:
        sid = None
        for message, category in zip(messages, categories):
            r = client.post("/api/chat", json={"message": message, "session_id": sid})
            assert r.status_code == 200, r.text
            body = r.json(); sid = body["session_id"]
            assert body["routing"]["category"] == category, body["routing"]
            assert body["message"]
        if messages == EXAMPLES[1][0]:
            assert body["state"]["cinema"]["parameters"]["date"] == "2026-11-07"
            assert body["results"][0]["data"]["showtimes"]
        if messages == EXAMPLES[2][0]:
            assert body["results"][0]["status"] == "ok"
        if messages == EXAMPLES[3][0]:
            assert body["results"][0]["status"] == "clarification"


def test_ascii_az_switching_filters_and_both_comparison():
    router = LocalRouter(Repositories.empty())
    state = SessionState()
    result = router.route("mene qulaqciq lazimdi", state)
    assert result.domains == [Domain.SHOPPING] and result.language == "az"
    assert result.intents[0].parameters.query == "headphones"
    state.shopping.intent = "search"; state.shopping.parameters.query = "headphones"
    state.last_active_domain = Domain.SHOPPING
    compare = router.route("Compare the first and second", state)
    assert compare.intents[0].parameters.result_positions == [1,2]
    color = router.route("Only black", state)
    assert color.intents[0].parameters.color == "black"


def test_live_saved_comparison_and_genre_reference():
    state = SessionState()
    state.cinema.last_result_ids = ["CP-a", "CP-b"]
    state.cinema.provider_snapshot = {"items": [{"id":"CP-a", "title":"Alpha", "genre":["Science Fiction / Adventure"]},
                                                {"id":"CP-b", "title":"Beta", "genre":["Drama"]}]}
    assert saved_ids(state.cinema, reference="the sci-fi one") == ["CP-a"]
    assert saved_ids(state.cinema, reference="both", compare=True) == ["CP-a", "CP-b"]


def test_november_7_branch_schedule_keeps_films_missing_from_today_homepage():
    future = '<table class="sessions_table"><tbody>' + showtime("future", "Future film", day="07.11.2026") + '</tbody></table>'
    http, _ = public_client(lambda r: httpx.Response(200, text=future, headers={"Content-Type":"text/html"})
                            if r.url.path.endswith("/ganjlik-mall/") else None)
    result = asyncio.run(CinemaPlusPublicProvider(http).search(CinemaParameters(cinema_name="Ganjlik", date=date(2026,11,7))))
    assert not result.error and result.items[0].title == "Future film"
    assert result.showtimes[0].date == date(2026,11,7)


def test_real_shopping_color_and_brand_filter_only_verified_matches():
    raw = {**ITEM, "title":"Sonivo Black Wireless Headphones", "brand":"Sonivo"}
    http = ProviderHTTP(transport=httpx.MockTransport(lambda r: httpx.Response(200,json={"data":[raw]})))
    provider = BuyWhereProvider(http)
    good = asyncio.run(provider.search(ShoppingParameters(query="headphones", color="black", brand="Sonivo")))
    assert not good.error and len(good.items) == 1
    assert not asyncio.run(provider.search(ShoppingParameters(query="headphones", color="red"))).items


def test_three_languages_all_domains_and_factual_direct_question():
    router = LocalRouter(Repositories.empty())
    for language, prompts in {
        "az": ["mene qulaqciq lazimdi", "Bakidan Istanbula sabah ucuslar", "bu gun filmler"],
        "en": ["Show headphones", "Flights from Baku to Istanbul tomorrow", "Movies today"],
        "ru": ["Покажи наушники", "Рейсы из Баку в Стамбул завтра", "Фильмы сегодня"]
    }.items():
        for prompt, domain in zip(prompts, ("shopping", "flights", "cinema")):
            result = router.route(prompt, SessionState())
            assert result.domains == [Domain(domain)] and result.language == language
    state = SessionState(last_active_domain=Domain.FLIGHTS)
    state.flights.intent = "search"
    result = router.route("The cheaper one, is it direct?", state)
    assert result.intents[0].parameters.stops is None
