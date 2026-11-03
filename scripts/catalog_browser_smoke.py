"""Desktop/mobile QA for real-provider contract shapes; no live API calls or secrets."""

from pathlib import Path

import httpx
from playwright.sync_api import expect, sync_playwright

from app.config import Settings
from scripts.provider_browser_smoke import local_server

HOME = '''<div class="today_list"><div class="sortable_movie_home"><h2><a href="/en/films/44/">44</a></h2>
<div class="poster_anim"><img src="/site/assets/files/44.jpg"></div><div class="go_film"><a href="/en/films/44/#sessions">SESSIONS</a></div></div></div>'''
ABOUT = '<a href="/en/cinema/about-cinemaplus/ganjlik-mall/">Ganjlik Mall</a>'
FILM = '''<a id="sessions"></a><table class="sessions_table"><tbody><tr data-date="03.11.2026">
<td><a href="/en/films/44/">44</a></td><td>19:30</td><td><a href="/en/cinema/about-cinemaplus/ganjlik-mall/">Ganjlik Mall</a></td>
<td>Hall 4</td><td></td><td>12 AZN</td></tr></tbody></table><ul class="movie_details1"><li><span>Duration</span><div class="detail">175 minutes</div></li></ul>'''
ITEM = {"itemId": "v1|123|0", "title": "Wireless headphones", "price": {"value": "49.99", "currency": "USD"},
        "image": {"imageUrl": "https://i.ebayimg.com/images/item.jpg"}, "itemWebUrl": "https://www.ebay.com/itm/123"}


def response(request):
    if request.url.host == "cinemastercard.az":
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /*.php", headers={"Content-Type": "text/plain"})
        pages = {"/en/": HOME, "/en/cinema/about-cinemaplus/": ABOUT, "/en/films/44/": FILM}
        return httpx.Response(200, text=pages[request.url.path], headers={"Content-Type": "text/html"})
    if request.url.host == "api.ebay.com":
        if "/item/" in request.url.path:
            return httpx.Response(200, json={**ITEM, "localizedAspects": [{"name": "Brand", "value": "Sony"}],
                "estimatedAvailabilities": [{"estimatedAvailabilityStatus": "IN_STOCK"}]})
        return httpx.Response(200, json={"total": 1, "itemSummaries": [ITEM]})
    raise AssertionError("Unexpected provider URL")


def main():
    screenshots = Path("docs/screenshots")
    with local_server(Settings(routing_mode="offline", ebay_token="browser-test"), response) as url, sync_playwright() as p:
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
                    before = page.locator(".turn.assistant").count()
                    box.fill(message)
                    page.get_by_role("button", name="Send message", exact=True).click()
                    expect(page.locator(".turn.assistant")).to_have_count(before + 1)
                    expect(box).to_be_enabled()
                    return page.locator(".turn.assistant").last

                products = send("Show headphones")
                expect(products).to_contain_text("eBay")
                expect(products).to_contain_text("49.99 USD")
                expect(products.locator("img.provider-image")).to_have_count(1)
                products.get_by_role("button", name="Details", exact=True).click()
                expect(page.locator(".turn.assistant")).to_have_count(2)
                expect(page.locator(".turn.assistant").last).to_contain_text("Sony")
                expect(page.locator(".turn.assistant").last).to_contain_text("estimated availability")
                page.screenshot(path=str(screenshots / f"shopping-{label}.png"), full_page=True)
                movies = send("Show movies")
                expect(movies).to_contain_text("CinemaPlus Azerbaijan")
                expect(movies).not_to_contain_text("TMDB metadata")
                expect(movies.get_by_role("link", name="Movie on CinemaPlus", exact=True)).to_have_attribute("href", "https://cinemastercard.az/en/films/44/")
                movies.get_by_role("button", name="Details", exact=True).click()
                expect(page.locator(".turn.assistant")).to_have_count(4)
                latest = page.locator(".turn.assistant").last
                expect(latest).to_contain_text("175 min")
                expect(latest).to_contain_text("Ganjlik Mall")
                expect(latest).to_contain_text("12.00 AZN listed price")
                expect(latest.locator(".showtime-card")).to_have_count(1)
                expect(latest).to_contain_text("Seats unknown")
                expect(latest.get_by_role("link", name="Official schedule", exact=True)).to_have_attribute("href", "https://cinemastercard.az/en/films/44/")
                page.screenshot(path=str(screenshots / f"cinemaplus-{label}.png"), full_page=True)
                blocked = send("Reserve 2 tickets for movie CP-44")
                expect(blocked).to_contain_text("do not verify seat availability or reserve tickets")
                assert not errors, errors
                assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
                context.close()
        finally:
            browser.close()
    print("Catalog browser QA passed: real CinemaPlus listing/schedule shapes and eBay product images/details on desktop/mobile.")


if __name__ == "__main__":
    main()
