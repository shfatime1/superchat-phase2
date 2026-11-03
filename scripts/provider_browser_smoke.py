"""Real browser QA with local provider contract stubs; no credentials/network calls.

Run with: python -m scripts.provider_browser_smoke
Requires requirements-dev.txt and Microsoft Edge. Saves Phase 2 QA screenshots.
"""

from contextlib import contextmanager
from pathlib import Path
import socket
from threading import Thread
import time
from urllib.request import urlopen

import httpx
from playwright.sync_api import expect, sync_playwright
import uvicorn

from app.config import Settings
from app.main import create_app


ROOT = Path(__file__).resolve().parents[1]


def provider_response(request):
    if request.url.host == "api.travelpayouts.com":
        rows = [{"origin": "GYD", "destination": "IST", "origin_airport": "GYD", "destination_airport": "IST",
                 "departure_at": "2026-12-01T10:00:00+04:00", "price": amount, "airline": "J2",
                 "flight_number": number, "transfers": 0, "duration": 190,
                 "link": "/search/GYD0112IST1"} for number, amount in (("75", 120), ("77", 150))]
        return httpx.Response(200, json={"success": True, "currency": "azn", "data": rows})
    if request.url.host == "api.themoviedb.org":
        movie = {"id": 11, "title": "Star Wars", "overview": "A space adventure.", "runtime": 121,
                 "vote_average": 8.2, "original_language": "en", "genres": [{"name": "Science Fiction"}]}
        return httpx.Response(200, json=movie if request.url.path.endswith("/movie/11") else {"results": [movie]})
    raise AssertionError("Unexpected provider request")


@contextmanager
def local_server(settings=None, handler=provider_response):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    app = create_app(settings or Settings(routing_mode="offline", travelpayouts_token="browser-test", tmdb_token="browser-test", cinema_provider="tmdb", shopping_provider="birmarket"))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = Thread(target=server.run, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                with urlopen(url + "/health", timeout=1):
                    break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError("Provider QA server failed to start")
        app.state.chat_service.engine.http.transport = httpx.MockTransport(handler)
        yield url
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def main():
    screenshots = ROOT / "docs" / "screenshots"
    screenshots.mkdir(exist_ok=True)
    with local_server() as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge", headless=True)
        try:
            for label, width, height in (("desktop", 1440, 1000), ("mobile", 390, 844)):
                context = browser.new_context(viewport={"width": width, "height": height})
                # Browser QA is offline, including optional attribution images.
                context.route("https://**/*", lambda route: route.abort())
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(url)

                def send(message):
                    box = page.locator("#message-input")
                    expect(box).to_be_enabled()
                    previous = page.locator(".turn.assistant").count()
                    box.fill(message)
                    page.get_by_role("button", name="Send message", exact=True).click()
                    expect(page.locator(".turn.assistant")).to_have_count(previous + 1)
                    expect(box).to_be_enabled()
                    expect(page.locator("#error")).to_be_hidden()
                    return page.locator(".turn.assistant").last

                flights = send("Show flights from GYD to IST on 2026-12-01")
                expect(flights.locator(".result-card")).to_have_count(2)
                expect(flights).to_contain_text("Aviasales / Travelpayouts · cached")
                expect(flights).to_contain_text("Seats, baggage and cabin: unknown")
                assert flights.get_by_role("button", name="Mock reserve").count() == 0
                checks = flights.get_by_role("checkbox")
                checks.nth(0).check()
                checks.nth(1).check()
                flights.get_by_role("button", name="Compare selected").click()
                expect(page.locator(".turn.assistant")).to_have_count(2)
                expect(page.locator(".turn.assistant").last.locator(".result-card")).to_have_count(2)
                shopping = send("Show shopping products")
                expect(shopping).to_contain_text("Birmarket · unavailable")
                expect(shopping.locator(".result-card")).to_have_count(0)
                movies = send("Show movies")
                expect(movies).to_contain_text("TMDB · " + ("live" if label == "desktop" else "cached"))
                expect(movies).to_contain_text("CinemaPlus screening unverified")
                movies.get_by_role("button", name="Details", exact=True).click()
                expect(page.locator(".turn.assistant")).to_have_count(5)
                expect(page.locator(".turn.assistant").last).to_contain_text("121 min")
                blocked = send("Reserve 2 tickets for movie TMDB-11")
                expect(blocked).to_contain_text("CinemaPlus Azerbaijan · unavailable")
                assert blocked.locator(".confirmation").count() == 0
                page.screenshot(path=str(screenshots / f"phase2-{label}.png"), full_page=True)
                assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth"), label
                assert not errors, errors
                context.close()
        finally:
            browser.close()
    print("Provider browser QA passed: desktop/mobile, flights/comparison, Birmarket authorization, TMDB details and CinemaPlus booking refusal.")


if __name__ == "__main__":
    main()
