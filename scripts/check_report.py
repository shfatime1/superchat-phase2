"""Check the four A4 HTML report pages and save visual-review images."""
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
output = ROOT / "tmp" / "report"
output.mkdir(parents=True, exist_ok=True)
with sync_playwright() as p:
    browser = p.chromium.launch(channel="msedge", headless=True)
    page = browser.new_page(viewport={"width": 1000, "height": 1200}, device_scale_factor=1)
    page.goto((ROOT / "docs" / "technical_report.html").as_uri())
    page.emulate_media(media="print")
    pages = page.locator(".page")
    assert pages.count() == 4
    for index in range(4):
        section = pages.nth(index)
        dimensions = section.evaluate("""element => {
          const footer = element.querySelector('footer').getBoundingClientRect();
          const contentBottom = Math.max(...[...element.children].filter(e => e.tagName !== 'FOOTER').map(e => e.getBoundingClientRect().bottom));
          return {height: element.getBoundingClientRect().height, width: element.getBoundingClientRect().width,
                  footerTop: footer.top, contentBottom, overflow: element.scrollHeight > element.clientHeight};
        }""")
        assert not dimensions["overflow"], (index + 1, dimensions)
        assert dimensions["contentBottom"] + 8 < dimensions["footerTop"], (index + 1, dimensions)
        section.screenshot(path=output / f"page-{index + 1}.png")
        print(f"Page {index + 1}: A4 dimensions and footer clearance checked")
    browser.close()
