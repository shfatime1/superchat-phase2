"""Targeted browser regression for the friendly ended-conversation option."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

root = Path(__file__).resolve().parents[1]
with sync_playwright() as p:
    browser = p.chromium.launch(channel="msedge", headless=True)
    page = browser.new_page()
    def serve(route):
        path = route.request.url.split("9999", 1)[1]
        if path == "/api/client":
            route.fulfill(json={"namespace": "test", "routing_mode": "offline"})
        elif path.startswith("/api/session/"):
            route.fulfill(status=404, json={"detail": "Session not found"})
        else:
            asset = root / "app" / "static" / (path.split("/")[-1] if path != "/" else "index.html")
            route.fulfill(path=str(asset))
    page.route("http://127.0.0.1:9999/**", serve)
    saved = [{"id": "old", "sessionId": "old-session", "title": "Saved plan", "turns": [{"role": "user", "content": "Keep my old messages"}], "archived": False}]
    page.add_init_script("localStorage.setItem('superchat.v1.test', " + json.dumps(json.dumps(saved)) + ");")
    page.goto("http://127.0.0.1:9999/")
    expect(page.locator("#notice")).to_contain_text("You can still read this conversation")
    expect(page.locator("body")).not_to_contain_text("server session has ended")
    expect(page.locator("#messages")).to_contain_text("Keep my old messages")
    page.get_by_role("button", name="Start a new conversation", exact=True).click()
    expect(page.locator("#message-input")).to_be_enabled()
    expect(page.locator("#welcome")).to_be_visible()
    expect(page.locator(".conversation-button")).to_contain_text("Saved plan")
    browser.close()
print("PASS: friendly option, retained history, new conversation, old conversation accessible")
