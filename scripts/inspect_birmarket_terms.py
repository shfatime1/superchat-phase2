"""Read the Birmarket public legal dialogs in an anonymous browser session.

Research only: no login, forms, search, cart, private API calls or app changes.
"""

from pathlib import Path
import sys

from playwright.sync_api import sync_playwright

OUTPUT = Path(__file__).resolve().parents[1] / "artifacts/provider-research/birmarket"


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        try:
            context = browser.new_context()
            page = context.new_page()
            page.goto("https://birmarket.az/", wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(1200)
            dismiss = page.locator('[data-info="close-icon-select-city-popup"]')
            if dismiss.is_visible():
                dismiss.click()
            page.locator('[data-info="footer-user-agreement-link"]').click(timeout=20000)
            page.wait_for_timeout(1500)
            print("Page", page.url, "title", page.title(), flush=True)
            print("Frames", [frame.url for frame in page.frames], flush=True)
            for index, frame in enumerate(page.frames):
                if frame.url.startswith(("https://birmarket.az/", "about:blank")):
                    text = frame.locator("body").inner_text(timeout=5000)
                    (OUTPUT / f"terms-dialog-{index}.txt").write_text(text, encoding="utf-8")
                    print(text[-30000:], flush=True)
            (OUTPUT / "terms-dialog.html").write_text(page.content(), encoding="utf-8")
            print("Dialogs", page.locator('[role="dialog"]').count(), flush=True)
            for frame in page.frames:
                for anchor in frame.locator('a[href$=".pdf"]').all():
                    print("Published PDF", anchor.get_attribute("href"), flush=True)
            context.close()
        finally:
            browser.close()


if __name__ == "__main__":
    main()
