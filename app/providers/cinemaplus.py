"""Official public HTML listings, never private ticketing/seat APIs.

Only robots-permitted public movie and cinema pages are requested. Published dates,
times, prices and links are retained; public listings do not establish seat inventory.
"""

from datetime import date, datetime
from hashlib import sha256
import re

from bs4 import BeautifulSoup
from pydantic import Field

from app.providers.http import ProviderFailure
from app.providers.models import MovieMetadata, Price, Provenance, ProviderResult, unavailable
from app.providers.public_cinema_http import PublicCinemaPages, ROOT, public_url
from app.schemas import Schema
from app.cinema_queries import normalized_cinema_parameters

HOME = ROOT + "/en/"
ABOUT = HOME + "cinema/about-cinemaplus/"
NOTICE = ("CinemaPlus Azerbaijan / CineMastercard public website listings. Published dates, times and "
          "prices may change; verify on the official page. Seats, final checkout prices and reservations "
          "are not available through this reader. No private APIs are used.")


class CinemaMovie(MovieMetadata):
    confirmed_cinemaplus_screening: bool = False
    listed_on_official_site: bool = True
    listing_date: date | None = None
    movie_url: str
    showtimes_url: str
    age_rating: str | None = None
    screening_languages: list[str] = Field(default_factory=list)


class CinemaLocation(Schema):
    id: str
    name: str
    source_url: str
    address: str | None = None


class PublicShowtime(Schema):
    id: str
    movie_id: str
    cinema_id: str
    movie_title: str
    cinema_name: str
    date: date
    time: str
    hall: str | None = None
    price: Price | None = None
    language: str | None = None
    formats: list[str] = Field(default_factory=list)
    source_url: str
    showtimes_url: str
    direct_showtime_url: str | None = None
    seats_available: int | None = None


class CinemaListings(ProviderResult[CinemaMovie]):
    cinemas: list[CinemaLocation] = Field(default_factory=list)
    showtimes: list[PublicShowtime] = Field(default_factory=list)
    screening_status: str = "listed_on_official_site"


def text(node):
    return node.get_text(" ", strip=True) if node else ""


def identifier(url, prefix):
    return prefix + url.rstrip("/").split("/")[-1]


def details_fields(soup):
    return {text(li.find("span", recursive=False)).casefold(): text(li.select_one(".detail"))
            for li in soup.select(".movie_details1 > li")}


class CinemaPlusPublicProvider:
    name = "CinemaPlus Azerbaijan"
    capabilities = {"currently_showing": True, "locations": True, "showtimes": True,
                    "ticket_prices": True, "seats": False, "film_details": True}

    def __init__(self, http):
        self.pages = PublicCinemaPages(http)

    @staticmethod
    def parse_movies(html):
        soup = BeautifulSoup(html, "html.parser")
        container = soup.select_one(".today_list")
        if container is None:
            raise ProviderFailure("public_layout_changed")
        active = soup.select_one("[data-df_date].active")
        listed_date = None
        if active:
            try:
                listed_date = datetime.strptime(active["data-df_date"], "%d.%m.%Y").date()
            except ValueError:
                pass
        rows = []
        for card in container.select(".sortable_movie_home"):
            a = card.select_one("h2 a[href]")
            url = public_url(a["href"]) if a else None
            if not url or "/films/" not in url or not text(a):
                continue
            image = card.select_one(".poster_anim img[src]")
            session = card.select_one(".go_film a[href]")
            languages = [text(t).split(":", 1)[1].strip() for t in card.select(".cc_tooltip > span")
                         if text(t).startswith("Movie language:")]
            rows.append(CinemaMovie(id=identifier(url, "CP-"), title=text(a), metadata_url=url,
                movie_url=url, showtimes_url=public_url(session["href"]) if session else url,
                poster_url=public_url(image["src"], "image") if image else None,
                age_rating=text(card.select_one(".movie_class")) or None, listing_date=listed_date,
                screening_languages=languages))
        if not rows:
            raise ProviderFailure("public_layout_changed")
        return list({r.id: r for r in rows}.values())

    @staticmethod
    def parse_locations(html):
        soup = BeautifulSoup(html, "html.parser")
        locations = {}
        for a in soup.select('a[href*="/en/cinema/about-cinemaplus/"]'):
            url = public_url(a["href"])
            if not url or url == ABOUT or not text(a) or text(a) in {"EN", "RU", "AZ"}:
                continue
            location = CinemaLocation(id=identifier(url, "CPC-"), name=text(a), source_url=url)
            locations[location.id] = location
        return list(locations.values())

    @staticmethod
    def parse_showtimes(html, source_url):
        soup = BeautifulSoup(html, "html.parser")
        if soup.select_one(".sessions_table") is None:
            raise ProviderFailure("public_layout_changed")
        rows, movies, cinemas = [], {}, {}
        for tr in soup.select(".sessions_table tbody tr[data-date]"):
            cols = tr.find_all("td", recursive=False)
            if len(cols) < 6:
                continue
            film, cinema = cols[0].find("a", href=True), cols[2].find("a", href=True)
            film_url = public_url(film["href"]) if film else None
            cinema_url = public_url(cinema["href"]) if cinema else None
            if not film_url or "/films/" not in film_url or not cinema_url:
                continue
            try:
                raw_day = tr["data-date"].strip()
                day = date.fromisoformat(raw_day) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw_day) else datetime.strptime(raw_day, "%d.%m.%Y").date()
                clock = datetime.strptime(text(cols[1]), "%H:%M").strftime("%H:%M")
            except ValueError:
                continue  # No guessed dates or times for malformed rows.
            movie_id, cinema_id = identifier(film_url, "CP-"), identifier(cinema_url, "CPC-")
            movie = CinemaMovie(id=movie_id, title=text(film), metadata_url=film_url, movie_url=film_url,
                showtimes_url=film_url, confirmed_cinemaplus_screening=True, listing_date=day)
            movies[movie_id] = movie
            cinemas[cinema_id] = CinemaLocation(id=cinema_id, name=text(cinema), source_url=cinema_url)
            amount = re.fullmatch(r"(\d+(?:[.,]\d+)?)\s*AZN", text(cols[5]))
            labels = [text(t) for t in cols[4].select(".cc_tooltip > span")]
            language = next((v.split(":", 1)[1].strip() for v in labels if v.startswith("Movie language:")), None)
            formats = [v.split(":", 1)[1].strip() for v in labels if v.startswith("Movie format:")]
            identity = "|".join((film_url, cinema_url, str(day), clock, text(cols[3])))
            rows.append(PublicShowtime(id="CPS-" + sha256(identity.encode()).hexdigest()[:16], movie_id=movie_id,
                cinema_id=cinema_id, movie_title=text(film), cinema_name=text(cinema), date=day, time=clock,
                hall=text(cols[3]) or None, price=Price(amount=amount[1].replace(",", "."), currency="AZN") if amount else None,
                language=language, formats=formats, source_url=source_url, showtimes_url=film_url))
        if soup.select(".sessions_table tbody tr[data-date]") and not rows:
            raise ProviderFailure("public_layout_changed")
        return list({r.id: r for r in rows}.values()), list(movies.values()), list(cinemas.values())

    async def search(self, p):
        p = normalized_cinema_parameters(p)
        try:
            doc = await self.pages.read(HOME)
            movies = self.parse_movies(doc.data)
            documents = [doc]
            locations, showtimes = [], []
            if p.min_rating is not None:
                raise ProviderFailure("rating_unavailable")
            if p.district:
                raise ProviderFailure("district_unavailable")
            if p.movie_title:
                query = p.movie_title.casefold().strip()
                movies = [m for m in movies if query in m.title.casefold()]
            if p.cinema_name or p.cinema_ids:
                about = await self.pages.read(ABOUT)
                documents.append(about)
                locations = self.parse_locations(about.data)
                matches = [c for c in locations if (not p.cinema_name or p.cinema_name.casefold() in c.name.casefold())
                           and (not p.cinema_ids or c.id in p.cinema_ids)]
                if len(matches) > 1:
                    raise ProviderFailure("choose_cinema")
                if matches:
                    page = await self.pages.read(matches[0].source_url)
                    documents.append(page)
                    showtimes, scheduled, locations = self.parse_showtimes(page.data, matches[0].source_url)
                    # A branch's published future films need not appear in today's
                    # homepage list. Keep verified schedule records for that date.
                    home_movies = {m.id: m for m in movies}
                    movies = [home_movies.get(m.id, m) for m in scheduled]
                    if p.movie_title:
                        movies = [m for m in movies if p.movie_title.casefold() in m.title.casefold()]
                else:
                    movies, locations = [], []
            elif p.movie_title or p.date or p.time or p.max_price_azn is not None or p.genre or p.language:
                # Bound public page reads. A named movie/cinema gives a focused complete source page.
                limited = movies[:6 if p.date else 3]
                for movie in limited:
                    page = await self.pages.read(movie.movie_url)
                    documents.append(page)
                    sessions, _, places = self.parse_showtimes(page.data, movie.movie_url)
                    self.enrich(movie, page.data)
                    showtimes.extend(sessions)
                    locations.extend(places)
                movies = limited
            else:
                about = await self.pages.read(ABOUT)
                documents.append(about)
                locations = self.parse_locations(about.data)
            if p.genre:
                canonical = lambda value: value.casefold().replace("science fiction", "sci-fi")
                movies = [m for m in movies if any(canonical(p.genre) in canonical(g) for g in m.genre)]
            if p.language:
                requested = {"english": "eng", "russian": "rus", "azerbaijani": "aze", "turkish": "tur",
                             "en": "eng", "ru": "rus", "az": "aze", "tr": "tur"}.get(p.language.casefold(), p.language.casefold())
                showtimes = [s for s in showtimes if (s.language or "").casefold() == requested]
            if p.date:
                showtimes = [s for s in showtimes if s.date == p.date]
            if p.time:
                requested_time = datetime.strptime(p.time, "%H:%M").strftime("%H:%M")
                showtimes = [s for s in showtimes if s.time == requested_time]
            if p.max_price_azn is not None:
                from decimal import Decimal
                showtimes = [s for s in showtimes if s.price and s.price.amount <= Decimal(str(p.max_price_azn))]
            constrained = p.date or p.time or p.max_price_azn is not None or p.language or p.cinema_name or p.cinema_ids
            if constrained:
                movies = [m for m in movies if any(s.movie_id == m.id for s in showtimes)]
            ids = {m.id for m in movies}
            showtimes = [s for s in showtimes if s.movie_id in ids]
            for movie in movies:
                movie.confirmed_cinemaplus_screening = any(s.movie_id == movie.id for s in showtimes)
            if p.sort_by:
                if p.sort_by not in {"title_asc", "title_desc", "time_asc", "price_asc", "price_desc"}:
                    raise ProviderFailure("invalid_sort")
                if p.sort_by.startswith("title"):
                    movies.sort(key=lambda m: m.title.casefold(), reverse=p.sort_by.endswith("desc"))
                elif p.sort_by.startswith("price"):
                    showtimes.sort(key=lambda s: (s.price.amount if s.price else float("inf")), reverse=p.sort_by.endswith("desc"))
            if p.sort_by not in {"price_asc", "price_desc"}:
                showtimes.sort(key=lambda s: (s.date, s.time, s.cinema_name))
            return CinemaListings(source=self.source(documents), items=movies,
                cinemas=list({c.id: c for c in locations}.values()), showtimes=showtimes,
                partial=True, screening_status="published_showtimes" if showtimes else "listed_on_official_site")
        except ProviderFailure as exc:
            return unavailable(self.name, HOME, "CinemaPlus public listings unavailable: " + exc.code.replace("_", " ") +
                ". Use the official site. Private booking/seat access requires CinemaPlus authorization.", exc.code, exc.retry_after)
        except (KeyError, ValueError, TypeError):
            self.pages.discard()
            return unavailable(self.name, HOME, "CinemaPlus public HTML could not be validated. Use the official site.", "public_layout_changed")

    @staticmethod
    def source(documents):
        return Provenance(provider="CinemaPlus Azerbaijan", status="cached" if all(d.cached for d in documents) else "live",
            fetched_at=min(d.fetched_at for d in documents), local_cache_hit=all(d.cached for d in documents),
            source_url=HOME, notice=NOTICE + " Coverage is limited to the published pages read; choose a movie or cinema for a focused schedule.")

    @staticmethod
    def enrich(movie, html):
        fields = details_fields(BeautifulSoup(html, "html.parser"))
        duration = re.fullmatch(r"(\d+)\s+minutes?", fields.get("duration", ""))
        if duration:
            movie.duration_min = int(duration[1])
        if fields.get("genre"):
            movie.genre = [fields["genre"]]
        movie.age_rating = fields.get("age restrictions") or movie.age_rating
        # Film synopses stay on the original page; do not republish full copyrighted descriptions.

    async def details(self, movie_id):
        if not re.fullmatch(r"CP-[\w-]+", movie_id):
            return unavailable(self.name, HOME, "Choose a CinemaPlus movie from the current listing.", "unknown_id")
        from app.schemas import CinemaParameters
        result = await self.search(CinemaParameters())
        if result.error:
            return result
        movie = next((m for m in result.items if m.id == movie_id), None)
        if movie is None:
            return unavailable(self.name, HOME, "That movie is not in the current public CinemaPlus listing.", "unknown_id")
        result = await self.search(CinemaParameters(movie_title=movie.title))
        if result.error:
            return result
        result.items = [m for m in result.items if m.id == movie_id]
        result.showtimes = [s for s in getattr(result, "showtimes", []) if s.movie_id == movie_id]
        return result
