"""A few endpoint-to-provider checks; Gemini responses are controlled, not live."""
import httpx
from fastapi.testclient import TestClient
from google.genai import errors

from app.config import Settings
from app.main import create_app
from test_phase2_ops import ITEM

PNG = b"\x89PNG\r\n\x1a\n" + bytes(32)
WAV = b"RIFF" + bytes(4) + b"WAVE" + bytes(32)


def test_image_identification_review_and_existing_shopping_flow(gemini):
    generate, enqueue = gemini
    enqueue({"identifiable": True, "query": "wireless headphones", "product_type": "headphones",
             "attributes": ["wireless", "over-ear"], "confidence": .86})
    with TestClient(create_app(Settings(api_key="test-key", routing_mode="offline"))) as client:
        client.app.state.chat_service.engine.http.transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"data": [ITEM]}))
        photo = client.post("/api/shopping/visual", content=PNG, headers={"Content-Type": "image/png"})
        assert photo.status_code == 200 and photo.json()["confidence"] == .86
        assert photo.json()["status"] == "ready"
        # Identification never submits a chat turn; the reviewed query does.
        assert not client.app.state.sessions._sessions
        result = client.post("/api/chat", json={"message": "Show me products matching " + photo.json()["query"]}).json()
        assert result["routing"]["domains"] == ["shopping"]
        assert result["results"][0]["data"]["products"]
        assert result["results"][0]["data"]["provider"]["provider"] == "BuyWhere"
        assert result["state"]["shopping"]["parameters"]["query"] == "wireless headphones"
        part = generate.call_args.kwargs["contents"].parts[0]
        assert part.inline_data.mime_type == "image/png" and part.inline_data.data == PNG


def test_az_en_ru_transcripts_reuse_budget_currency_and_routing(gemini):
    _, enqueue = gemini
    phrases = [("az", "500$ dan ucuz notebooklar"), ("en", "laptops under $500"), ("ru", "ноутбуки до 500 долларов")]
    enqueue(*[{"speech_detected": True, "text": text, "language": lang} for lang, text in phrases])
    with TestClient(create_app(Settings(api_key="test-key", routing_mode="offline"))) as client:
        client.app.state.chat_service.engine.http.transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"data": []}))
        for language, text in phrases:
            transcript = client.post("/api/media/transcribe", content=WAV, headers={"Content-Type": "audio/wav"}).json()
            assert transcript["text"] == text and transcript["language"] == language
            answer = client.post("/api/chat", json={"message": transcript["text"]}).json()
            p = answer["state"]["shopping"]["parameters"]
            assert answer["routing"]["domains"] == ["shopping"]
            assert p["query"] == "laptops" and p["currency"] == "USD" and p["max_price"] == 500


def test_uncertain_images_silence_and_sanitized_provider_errors(gemini):
    _, enqueue = gemini
    enqueue({"identifiable": False, "confidence": .1},
            {"speech_detected": False, "text": "invented words", "language": "en"},
            errors.ClientError(429, {"error": {"message": "SECRET"}}),
            httpx.ReadTimeout("SECRET"))
    with TestClient(create_app(Settings(api_key="test-key", routing_mode="offline"))) as client:
        assert client.post("/api/shopping/visual", content=PNG, headers={"Content-Type": "image/png"}).json()["status"] == "uncertain"
        silent = client.post("/api/media/transcribe", content=WAV, headers={"Content-Type": "audio/wav"}).json()
        assert silent["text"] == "" and not silent["speech_detected"]
        failed = client.post("/api/shopping/visual", content=PNG, headers={"Content-Type": "image/png"})
        assert failed.status_code == 429 and "SECRET" not in failed.text
        assert failed.headers["Retry-After"] == "30"
        timed = client.post("/api/media/transcribe", content=WAV, headers={"Content-Type": "audio/wav"})
        assert timed.status_code == 504 and "SECRET" not in timed.text


def test_upload_guards_missing_key_and_session_ownership():
    with TestClient(create_app(Settings(routing_mode="offline"))) as client:
        assert client.post("/api/shopping/visual", content=b"bad", headers={"Content-Type": "image/png"}).status_code == 415
        assert client.post("/api/shopping/visual", content=PNG + bytes(4 * 1024 * 1024), headers={"Content-Type": "image/png"}).status_code == 413
        missing = client.post("/api/shopping/visual", content=PNG, headers={"Content-Type": "image/png"})
        assert missing.status_code == 503 and missing.json()["detail"] == "gemini_not_configured"
        assert client.post("/api/media/transcribe", content=WAV, headers={"Content-Type": "audio/wav", "Origin": "https://other.test"}).status_code == 403
        session = client.post("/api/chat", json={"message": "Flights"}).json()["session_id"]
        client.cookies.clear()
        assert client.post("/api/media/transcribe?session_id=" + session, content=WAV, headers={"Content-Type": "audio/wav"}).status_code == 404
