"""Contracts based on inspected public HTML; tests never read live pages or mock JSON catalogs."""

import asyncio

import httpx
import pytest

from app.config import Settings
from app.providers.cinemaplus import CinemaPlusPublicProvider, HOME, ABOUT
from app.providers.engine import ProviderDomainEngine
from app.providers.http import ProviderHTTP
from app.providers.public_cinema_http import public_url, robots_allowed
from app.schemas import CinemaParameters, RoutingResult
from app.state import SessionState

HOME_HTML = '''<div class="today_list"><div class="sortable_movie_home"><h2><a href="/en/films/44/">44</a></h2>
<span class="movie_class">12+</span><div class="poster_anim"><img src="/site/assets/files/44.jpg"></div>
<span class="cc_tooltip"><span>Movie language: Aze</span></span><div class="go_film"><a href="/en/films/44/#sessions">SESSIONS</a></div></div>
<div class="sortable_movie_home"><h2><a href="/en/films/verity/">Verity</a></h2><div class="go_film"><a href="/en/films/verity/#sessions">SESSIONS</a></div></div></div>
<a class="active" data-df_date="03.11.2026">Today</a>'''
ABOUT_HTML = '''<a href="/en/cinema/about-cinemaplus/">About us</a>
<a href="/en/cinema/about-cinemaplus/ganjlik-mall/">Ganjlik Mall</a>
<a href="/en/cinema/about-cinemaplus/28-mall/">28 Mall</a>'''


def showtime(film="44", title="44", day="03.11.2026", clock="19:30", price="12.00 AZN"):
    return f'''<tr data-date="{day}"><td><a href="/en/films/{film}/">{title}</a></td><td>{clock}</td>
<td><a href="/en/cinema/about-cinemaplus/ganjlik-mall/">Ganjlik Mall</a></td><td>Hall 4</td>
<td><span class="cc_tooltip"><span>Movie format: 2D</span></span><span class="cc_tooltip"><span>Movie language: Aze</span></span></td><td>{price}</td>
<td><div data-session="999"><input disabled placeholder="Places"></div></td></tr>'''


FILM_HTML = '<a id="sessions"></a><table class="sessions_table"><tbody>' + showtime() + showtime(day="04.11.2026", price="10.00 AZN") + '''</tbody></table>
<ul class="movie_details1"><li><span>Duration</span><div class="detail">175 minutes</div></li>
<li><span>Genre</span><div class="detail">War Drama</div></li><li><span>Age restrictions</span><div class="detail">12+</div></li></ul>'''
CINEMA_HTML = '<table class="sessions_table"><tbody>' + showtime() + showtime("verity", "Verity", clock="21:30") + '</tbody></table>'


async def no_sleep(delay):
    pass


def client(handler=None):
    paths = []
    def response(request):
        paths.append(request.url.path)
        if handler:
            custom = handler(request)
            if custom is not None:
                return custom
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /*.php\nDisallow: /*.log\n", headers={"Content-Type": "text/plain"})
        pages = {"/en/": HOME_HTML, "/en/cinema/about-cinemaplus/": ABOUT_HTML,
            "/en/films/44/": FILM_HTML, "/en/films/verity/": FILM_HTML.replace('/44/', '/verity/').replace('>44<', '>Verity<'),
            "/en/cinema/about-cinemaplus/ganjlik-mall/": CINEMA_HTML}
        if request.url.path in pages:
            return httpx.Response(200, text=pages[request.url.path], headers={"Content-Type": "text/html; charset=utf-8"})
        if request.url.host == "api.themoviedb.org":
            return httpx.Response(200, json={"results": [{"id": 11, "title": "Star Wars"}]})
        pytest.fail("Unexpected public/private URL: " + str(request.url))
    return ProviderHTTP(transport=httpx.MockTransport(response), retries=0, sleep=no_sleep), paths


def run(awaitable):
    return asyncio.run(awaitable)


def routing(operation="search", **parameters):
    return RoutingResult.model_validate({"category": "cinema", "domains": ["cinema"], "intents": [
        {"domain": "cinema", "intent": operation, "parameters": parameters}]})


def test_official_movies_locations_links_and_cached_status():
    http, paths = client()
    provider = CinemaPlusPublicProvider(http)
    first = run(provider.search(CinemaParameters()))
    assert first.error is None and first.source.provider == "CinemaPlus Azerbaijan" and first.source.status == "live"
    assert [m.id for m in first.items] == ["CP-44", "CP-verity"]
    assert first.items[0].movie_url == HOME + "films/44/"
    assert first.items[0].showtimes_url == HOME + "films/44/#sessions"
    assert first.items[0].confirmed_cinemaplus_screening is False
    assert first.items[0].listing_date.isoformat() == "2026-11-03"
    assert len(first.cinemas) == 2 and all(c.address is None for c in first.cinemas)
    second = run(provider.search(CinemaParameters()))
    assert second.source.status == "cached" and second.source.fetched_at == first.source.fetched_at
    assert paths == ["/robots.txt", "/en/", "/en/cinema/about-cinemaplus/"]


def test_named_movie_has_dated_showtimes_prices_and_no_seat_claims():
    http, paths = client()
    result = run(CinemaPlusPublicProvider(http).search(CinemaParameters(movie_title="44", date="2026-11-04")))
    assert result.error is None and len(result.showtimes) == 1
    row = result.showtimes[0]
    assert row.date.isoformat() == "2026-11-04" and row.time == "19:30"
    assert row.price.amount == 10 and row.price.currency == "AZN"
    assert row.seats_available is row.direct_showtime_url is None
    assert row.source_url == HOME + "films/44/" and row.showtimes_url == HOME + "films/44/"
    assert result.items[0].duration_min == 175 and result.items[0].genre == ["War Drama"]
    assert result.items[0].confirmed_cinemaplus_screening is True
    assert not any(".php" in path or "api" in path for path in paths)


def test_cinema_filter_uses_actual_location_link_and_schedule():
    http, paths = client()
    result = run(CinemaPlusPublicProvider(http).search(CinemaParameters(cinema_name="Ganjlik", max_price_azn=12)))
    assert result.error is None and len(result.showtimes) == 2 and len(result.items) == 2
    assert "/en/cinema/about-cinemaplus/ganjlik-mall/" in paths
    assert all(s.cinema_name == "Ganjlik Mall" for s in result.showtimes)


@pytest.mark.parametrize("params", [dict(date="2030-01-01"), dict(time="22:00"), dict(max_price_azn=1)])
def test_unpublished_dates_times_prices_are_not_invented(params):
    http, _ = client()
    result = run(CinemaPlusPublicProvider(http).search(CinemaParameters(movie_title="44", **params)))
    assert result.error is None and result.items == [] and result.showtimes == []


def test_robots_disallow_stops_before_fetching_movie_pages():
    http, paths = client(lambda r: httpx.Response(200, text="User-agent: *\nDisallow: /en/", headers={"Content-Type": "text/plain"})
        if r.url.path == "/robots.txt" else None)
    result = run(CinemaPlusPublicProvider(http).search(CinemaParameters()))
    assert result.error.code == "robots_disallowed" and paths == ["/robots.txt"]


def test_robots_wildcards_specific_agents_and_allow_priority():
    policy = "User-agent: *\nDisallow: /en/*\nAllow: /en/$\n"
    assert robots_allowed(policy, HOME)
    assert not robots_allowed(policy, HOME + "films/44/")
    policy += "User-agent: SuperChat\nDisallow: /en/films/*\nAllow: /en/films/44/$\n"
    assert robots_allowed(policy, HOME + "films/44/")
    assert not robots_allowed(policy, HOME + "films/verity/")
    assert robots_allowed(policy, ABOUT)


def test_excessive_published_crawl_delay_stops_instead_of_overriding_policy():
    http, paths = client(lambda r: httpx.Response(200, text="User-agent: *\nCrawl-delay: 120", headers={"Content-Type": "text/plain"})
        if r.url.path == "/robots.txt" else None)
    result = run(CinemaPlusPublicProvider(http).search(CinemaParameters()))
    assert result.error.code == "crawl_delay_exceeds_request_budget" and paths == ["/robots.txt"]


def test_published_crawl_delay_applies_to_first_html_request():
    http, _ = client(lambda r: httpx.Response(200, text="User-agent: *\nCrawl-delay: 5", headers={"Content-Type": "text/plain"})
        if r.url.path == "/robots.txt" else None)
    delays = []
    async def capture(delay):
        delays.append(delay)
    http.sleep, http.clock = capture, lambda: 0
    result = run(CinemaPlusPublicProvider(http).search(CinemaParameters()))
    assert result.error is None and delays[0] >= 5


@pytest.mark.parametrize("status,code", [(403, "public_access_restricted"), (429, "rate_limited"), (302, "public_page_unavailable")])
def test_public_access_restrictions_and_redirects_are_not_bypassed(status, code):
    http, _ = client(lambda r: httpx.Response(status, headers={"Retry-After": "30", "Location": "https://other.example/"}) if r.url.path == "/en/" else None)
    result = run(CinemaPlusPublicProvider(http).search(CinemaParameters()))
    assert result.error.code == code and result.source.status == "unavailable"


def test_url_allowlist_and_malformed_html_fail_closed():
    assert public_url("https://other.example/en/films/44/") is None
    assert public_url("/ajax.php") is None and public_url("/en/films/44/?session=123") is None
    assert public_url("/en/films/../../private/") is None
    http, _ = client(lambda r: httpx.Response(200, text="<html>Access challenge</html>", headers={"Content-Type": "text/html"}) if r.url.path == "/en/" else None)
    result = run(CinemaPlusPublicProvider(http).search(CinemaParameters()))
    assert result.error.code == "public_layout_changed"
    with pytest.raises(Exception, match="public_layout_changed"):
        CinemaPlusPublicProvider.parse_showtimes(FILM_HTML.replace('data-date="03.11.2026"', 'data-date="missing"').replace('data-date="04.11.2026"','data-date="missing"'), HOME)


def test_official_source_has_priority_over_configured_tmdb_and_details_work():
    http, paths = client()
    engine = ProviderDomainEngine(Settings(tmdb_token="test"), http)
    state = SessionState()
    result = engine.execute(routing(), state)[0]
    assert result.data["provider"]["provider"] == "CinemaPlus Azerbaijan"
    details = engine.execute(routing("details", movie_ids=["CP-44"]), state)[0]
    assert details.data["movies"][0]["duration_min"] == 175 and len(details.data["showtimes"]) == 2
    assert state.cinema.selected_ids == ["CP-44"] and len(state.cinema.last_showtime_ids) == 2
    assert not any(path.startswith("/3/") for path in paths)
    blocked = engine.execute(routing("reserve", movie_ids=["CP-44"], tickets=2), state)[0]
    assert blocked.code == "unsupported_operation" and not state.cinema.reservations


def test_tmdb_only_falls_back_after_official_failure_and_is_labeled():
    http, paths = client(lambda r: httpx.Response(403) if r.url.path == "/en/" else None)
    engine = ProviderDomainEngine(Settings(tmdb_token="test"), http)
    result = engine.execute(routing(), SessionState())[0]
    assert result.data["provider"]["provider"] == "TMDB" and result.data["primary_provider_error"]["code"] == "public_access_restricted"
    assert result.data["showtimes"] == [] and result.data["movies"][0]["confirmed_cinemaplus_screening"] is False
    assert paths.index("/en/") < paths.index("/3/discover/movie")


def test_no_fallback_on_valid_empty_official_search():
    http, paths = client()
    result = ProviderDomainEngine(Settings(tmdb_token="test"), http).execute(routing(movie_title="Missing movie"), SessionState())[0]
    assert result.status == "no_results" and result.data["provider"]["provider"] == "CinemaPlus Azerbaijan"
    assert not any(path.startswith("/3/") for path in paths)
