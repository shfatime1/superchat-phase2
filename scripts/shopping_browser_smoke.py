"""Desktop/mobile Shopping QA with offline API contract stubs, never production data."""

from pathlib import Path

import httpx
from playwright.sync_api import expect, sync_playwright

from app.config import Settings
from scripts.provider_browser_smoke import local_server

ITEM = {"id": "8242752712", "title": "Bluetooth headphones", "price": {"amount": "13.99", "currency": "USD"},
    "merchant": "amazon_us", "url": "https://www.amazon.com/dp/B0H3P59RQZ",
    "image_url": "https://m.media-amazon.com/images/I/71FSiyK+FCL.jpg", "availability": "local",
    "category_path": ["Electronics", "Headphones"], "price_as_of": "2026-01-01T00:00:00Z",
    "affiliate_redirect_url": "https://buywhere.ai/r/direct/8242752712?source=product_card"}


def response(request):
    assert request.url.host == "api.buywhere.ai" and request.url.path == "/v1/products/search"
    assert "Authorization" not in request.headers
    return httpx.Response(200, json={"data": [ITEM, {**ITEM, "id": "2", "title": "Second headphones",
        "price": {"amount": "19.99", "currency": "USD"}, "price_as_of": None}]})


def main():
    output = Path("artifacts/shopping-browser-qa")
    output.mkdir(parents=True, exist_ok=True)
    with local_server(Settings(routing_mode="offline"), response) as url, sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        try:
            for label, width, height in (("desktop", 1440, 1000), ("mobile", 390, 844)):
                context = browser.new_context(viewport={"width": width, "height": height})
                context.route("https://**/*", lambda route: route.fulfill(status=200, content_type="image/svg+xml",
                    body='<svg xmlns="http://www.w3.org/2000/svg" width="120" height="160"><rect width="120" height="160" fill="#d7e6d8"/></svg>')
                    if route.request.resource_type == "image" else route.abort())
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda err: errors.append(str(err)))
                page.goto(url)

                def send(message):
                    box = page.locator("#message-input")
                    expect(box).to_be_enabled()
                    count = page.locator(".turn.assistant").count()
                    box.fill(message)
                    page.get_by_role("button", name="Send message", exact=True).click()
                    expect(page.locator(".turn.assistant")).to_have_count(count + 1)
                    expect(box).to_be_enabled()
                    return page.locator(".turn.assistant").nth(count)

                first = send("Show headphones under 100 USD")
                expect(first).to_contain_text("BuyWhere")
                expect(first.locator(".result-card")).to_have_count(2)
                expect(first.locator("img.provider-image")).to_have_count(2)
                expect(first.locator(".result-card").first).to_contain_text("13.99 USD")
                expect(first.locator(".result-card").first).to_contain_text("Older than 24 hours")
                expect(first.locator(".result-card").last).to_contain_text("Catalog price date: unknown")
                expect(first).to_contain_text("Stock: unverified")
                expect(first.get_by_role("link", name="View retailer offer").first).to_have_attribute("href", ITEM["affiliate_redirect_url"])
                first.get_by_role("button", name="Details", exact=True).first.click()
                expect(page.locator(".turn.assistant")).to_have_count(2)
                details = page.locator(".turn.assistant").last
                expect(details).to_contain_text("cached")
                expect(details.locator(".result-card")).to_have_count(1)
                checks = first.get_by_role("checkbox")
                checks.nth(0).check()
                checks.nth(1).check()
                first.get_by_role("button", name="Compare selected").click()
                expect(page.locator(".turn.assistant")).to_have_count(3)
                expect(page.locator(".turn.assistant").last.locator(".result-card")).to_have_count(2)
                blocked = send("Add 1 BW-8242752712 to my cart")
                expect(blocked).to_contain_text("cannot verify availability or perform reservations")
                assert not errors, errors
                assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
                page.screenshot(path=str(output / f"{label}.png"), full_page=True)
                context.close()
        finally:
            browser.close()
    print("Shopping browser QA passed on desktop/mobile: images, links, price dates, saved Details, Compare and purchase refusal.")


if __name__ == "__main__":
    main()
