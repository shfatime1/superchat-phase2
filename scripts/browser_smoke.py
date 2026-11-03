"""Optional end-to-end QA: starts/stops its own offline server; no Gemini cost.

Install requirements-dev.txt and an Edge browser, then run this script.
"""
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SCREENSHOTS = ROOT / "docs" / "screenshots"


def main():
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    env = dict(os.environ, SUPERCHAT_DATA_MODE="fixtures", SUPERCHAT_ROUTING_MODE="offline", GEMINI_API_KEY="", COOKIE_SECURE="false")
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    try:
        for _ in range(100):
            try:
                with urlopen(url + "/health", timeout=1):
                    break
            except OSError:
                if process.poll() is not None:
                    raise RuntimeError("Local smoke-test server exited")
                time.sleep(0.1)
        else:
            raise RuntimeError("Local smoke-test server did not start")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="msedge", headless=True)
            desktop = browser.new_context(viewport={"width": 1440, "height": 1000})
            page = desktop.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(url)
            expect(page.locator("#message-input")).to_be_enabled()
            page.screenshot(path=SCREENSHOTS / "desktop-welcome.png", full_page=True)
            page.get_by_role("button", name="Find your next escape", exact=False).click()
            expect(page.locator(".result-card")).to_have_count(3)
            expect(page.get_by_role("button", name="Compare selected")).to_be_disabled()
            page.get_by_role("checkbox", name="Select F013 for comparison").check()
            page.get_by_role("checkbox", name="Select F002 for comparison").check()
            page.get_by_role("button", name="Compare selected").click()
            expect(page.locator(".comparison-wrap tbody tr")).to_have_count(2)

            def send(message):
                box = page.locator("#message-input")
                expect(box).to_be_enabled()
                previous = page.locator(".turn.assistant").count()
                box.fill(message)
                page.get_by_role("button", name="Send message", exact=True).click()
                expect(page.locator(".turn.assistant")).to_have_count(previous + 1)
                expect(box).to_be_enabled()
                expect(page.locator("#error")).to_be_hidden()

            send("Show headphones under 100 AZN")
            latest = page.locator(".turn.assistant").last
            latest.locator(".quantity-input").fill("2")
            latest.get_by_role("button", name="Add to cart", exact=True).click()
            expect(page.locator(".cart-total").last).to_contain_text("179.80")
            page.locator(".cart-line").last.get_by_role("button", name="Remove 1").click()
            expect(page.locator(".cart-total").last).to_contain_text("89.90")
            send("What movies are playing tonight?")
            latest = page.locator(".turn.assistant").last
            sold = latest.locator(".showtime-card").filter(has_text="S003")
            expect(sold.get_by_role("button", name="Mock tickets")).to_be_disabled()
            showtime = latest.locator(".showtime-card").filter(has_text="S001")
            showtime.get_by_role("button", name="Mock tickets").click()
            expect(page.locator(".confirmation")).to_have_count(1)
            expect(page.locator(".confirmation")).to_contain_text("No payment")
            send("Back to flights")
            expect(page.locator(".turn.assistant").last.locator(".result-card")).to_have_count(2)
            send("Only direct")
            expect(page.locator(".turn.assistant").last.locator(".result-card")).to_have_count(2)
            expect(page.locator(".turn.assistant").last).not_to_contain_text("F013")
            page.screenshot(path=SCREENSHOTS / "desktop-conversation.png", full_page=True)
            before = page.locator(".turn").count()
            page.reload()
            expect(page.locator(".turn")).to_have_count(before)
            expect(page.locator(".cart-total").last).to_contain_text("89.90")

            # Simulate a lost HTTP response after the reservation actually committed.
            captured = []
            def lost_response(route):
                captured.append(route.request.post_data_json)
                route.fetch()
                route.abort("failed")
            page.route("**/api/chat", lost_response, times=1)
            page.locator("#message-input").fill("Reserve flight F002 for 1 passenger")
            page.get_by_role("button", name="Send message", exact=True).click()
            expect(page.get_by_role("button", name="Retry safely")).to_be_visible()
            page.get_by_role("button", name="Retry safely").click()
            expect(page.locator(".confirmation")).to_have_count(2)
            expect(page.locator("#error")).to_be_hidden()
            sid = captured[0]["session_id"]
            state = desktop.request.get(url + "/api/session/" + sid).json()
            assert len(state["flights"]["reservations"]) == 1
            assert state["shopping"]["cart"] == {"P001": 1}

            page.locator("#new-chat").click()
            expect(page.locator("#welcome")).to_be_visible()
            send("Show cart")
            expect(page.locator(".cart-total")).to_contain_text("0.00")
            send("Find a flight from Baku to Istanbul on Friday and a backpack under 100 AZN")
            expect(page.locator(".turn.assistant").last.locator(".result-section")).to_have_count(2)
            send("The first one")
            assert not page.locator(".turn.assistant").last.locator(".result-card").count()

            # Different browser identity cannot read even a known session ID.
            mobile = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
            phone = mobile.new_page()
            phone.on("pageerror", lambda error: errors.append(str(error)))
            phone.goto(url)
            expect(phone.locator("#message-input")).to_be_enabled()
            assert mobile.request.get(url + "/api/session/" + sid).status == 404
            assert phone.locator(".conversation-button").count() == 0
            assert phone.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            phone.screenshot(path=SCREENSHOTS / "mobile-welcome.png", full_page=True)
            phone.get_by_role("button", name="A little upgrade", exact=False).click()
            expect(phone.locator(".result-card")).to_have_count(1)
            phone.get_by_role("button", name="Add to cart", exact=True).click()
            expect(phone.locator(".cart-total")).to_contain_text("89.90")
            expect(phone.locator("#error")).to_be_hidden()
            assert phone.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            phone.screenshot(path=SCREENSHOTS / "mobile-conversation.png", full_page=True)
            phone.locator("#menu-button").click()
            expect(phone.locator("#sidebar")).to_have_class("sidebar open")
            phone.locator("#new-chat").click()
            expect(phone.locator("#welcome")).to_be_visible()
            expect(phone.locator("#sidebar")).to_have_class("sidebar")

            # Restart/expired session is archived, never silently replayed.
            page.route("**/api/session/*", lambda route: route.fulfill(status=404, json={"detail": "Session not found"}))
            page.reload()
            expect(page.locator("#notice")).to_contain_text("You can still read this conversation")
            expect(page.locator("#message-input")).to_be_disabled()
            page.locator("#new-chat").click()
            expect(page.locator("#message-input")).to_be_enabled()
            assert not errors, errors
            browser.close()
        print("PASS: desktop/mobile UI, comparisons, cart, tickets, switching, refresh, safe retry, mixed requests, isolation, expired sessions; zero JS errors.")
        print("Screenshots: docs/screenshots/")
    finally:
        process.terminate()
        process.wait(timeout=10)


if __name__ == "__main__":
    main()
