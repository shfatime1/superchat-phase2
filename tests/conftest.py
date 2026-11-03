import json
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.responses import ResponsePlan, ResponseSection


@pytest.fixture(autouse=True)
def block_live_gemini(monkeypatch):
    # No test may construct a real SDK client, even if a real .env exists.
    factory = MagicMock(name="GeminiClient")
    client = factory.return_value.__enter__.return_value
    client.models.generate_content.side_effect = AssertionError("Unmocked Gemini call")
    monkeypatch.setattr("app.routing.genai.Client", factory)
    # Retain the Part 1 routing queues. Formulation is mocked independently;
    # dedicated Part 2 tests exercise its real SDK adapter and fallback.
    monkeypatch.setattr("app.responses.GeminiResponseFormulator.generate_plan",
                        lambda self, message, language, outcomes: ResponsePlan(
                            sections=[ResponseSection(result_index=i) for i in range(len(outcomes))]))
    return factory


@pytest.fixture
def gemini(block_live_gemini):
    generate = block_live_gemini.return_value.__enter__.return_value.models.generate_content

    def enqueue(*results):
        generate.side_effect = [
            result if isinstance(result, Exception) else MagicMock(text=json.dumps(result))
            for result in results
        ]

    return generate, enqueue


@pytest.fixture
def client():
    with TestClient(create_app(Settings(data_mode="fixtures", api_key="unit-test-placeholder", routing_mode="strict"))) as test_client:
        yield test_client


def route(category, domain=None, parameters=None, intent="search", **extra):
    result = {"category": category, "domains": [domain] if domain else [],
              "intents": [{"domain": domain, "intent": intent,
                           "parameters": parameters or {}}] if domain else []}
    result.update(extra)
    return result
