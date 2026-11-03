"""Read a small set of public pages for reproducible CinemaPlus access research.

No private APIs, JavaScript execution, login or ticket/seat endpoints are used.
"""

from pathlib import Path
import asyncio
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

ROOT = "https://cinemastercard.az"
AGENT = "SuperChat/2.0 (public cinema listings research)"
PATHS = ("/en/", "/en/films/44/", "/en/cinema/about-cinemaplus/ganjlik-mall/", "/ru/rules/")


def main():
    if "--verify-provider" in sys.argv:
        from app.config import Settings
        from app.providers.cinemaplus import CinemaPlusPublicProvider
        from app.providers.http import ProviderHTTP
        from app.schemas import CinemaParameters
        result = asyncio.run(CinemaPlusPublicProvider(ProviderHTTP(timeout=20, retries=0)).search(
            CinemaParameters(movie_title="44", date=Settings().reference_date())))
        if result.error:
            raise RuntimeError(result.error.code)
        print("Provider:", result.source.provider, "Status:", result.source.status,
              "Movies:", len(result.items), "Dated showtimes:", len(result.showtimes), "Cinemas:", len(result.cinemas))
        if result.showtimes:
            row = result.showtimes[0]
            print("Published date/time:", row.date, row.time, "Listed price:", row.price.amount if row.price else None)
            print("Official URL:", row.showtimes_url, "Seat availability:", row.seats_available)
        return
    target = Path("artifacts/provider-research/cinemaplus")
    target.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=20, headers={"User-Agent": AGENT}, follow_redirects=False) as client:
        robots = client.get(ROOT + "/robots.txt")
        robots.raise_for_status()
        (target / "robots.txt").write_text(robots.text, encoding="utf-8")
        from app.providers.public_cinema_http import robots_allowed
        for path in PATHS:
            url = ROOT + path
            if not robots_allowed(robots.text, url, AGENT):
                print(path, "robots_disallowed")
                continue
            response = client.get(url)
            filename = path.strip("/").replace("/", "_") + ".html"
            if response.status_code == 200 and "text/html" in response.headers.get("content-type", ""):
                (target / filename).write_text(response.text, encoding="utf-8")
            print(path, response.status_code, len(response.content), filename)


if __name__ == "__main__":
    main()
