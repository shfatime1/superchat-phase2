"""Conservative access to robots-permitted CinemaPlus public HTML pages only."""

import re
from threading import RLock
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

from app.providers.http import Document, ProviderFailure
from app.providers.models import utcnow
from app.diagnostics import cache_context, current, http_call, http_status, http_attempt

ROOT = "https://cinemastercard.az"
AGENT = "SuperChat/2.0 (public cinema listings; cached, read-only)"


def robots_allowed(body, url, agent=AGENT):
    """Apply user-agent specificity, longest matching path, * and $ (RFC 9309).

    urllib.robotparser's path-prefix check alone does not handle wildcard rules.
    URL access is additionally restricted by the independent public-page allowlist.
    """
    groups, agents, rules = [], [], []
    for raw in body.splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, value = [part.strip() for part in line.split(":", 1)]
        key = key.casefold()
        if key == "user-agent":
            if rules:
                groups.append((agents, rules))
                agents, rules = [], []
            agents.append(value.casefold())
        elif key in {"allow", "disallow"} and agents:
            if value:
                rules.append((key, value))
    if agents:
        groups.append((agents, rules))
    eligible = [(len(a) if a != "*" else 0, entries) for names, entries in groups for a in names
                if a == "*" or a in agent.casefold()]
    if not eligible:
        return True
    priority = max(rank for rank, _ in eligible)
    path = urlparse(url).path
    matches = []
    for rank, entries in eligible:
        if rank != priority:
            continue
        for kind, pattern in entries:
            ending = pattern.endswith("$")
            core = pattern[:-1] if ending else pattern
            expression = "^" + re.escape(core).replace(r"\*", ".*") + ("$" if ending else "")
            if re.search(expression, path):
                matches.append((len(core.replace("*", "")), kind == "allow"))
    return max(matches)[1] if matches else True


def public_url(value, kind="page"):
    from urllib.parse import urljoin
    url = urljoin(ROOT, value or "")
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc != "cinemastercard.az" or parsed.query:
        return None
    allowed = r"/en/(?:films/[\w-]+/|cinema/about-cinemaplus/(?:[\w-]+/)?)?"
    if kind == "image":
        allowed = r"/site/assets/files/[\w/.-]+"
    if not re.fullmatch(allowed, parsed.path):
        return None
    return url


class PublicCinemaPages:
    """Shares transport configuration, without changing the working JSON API transport."""

    def __init__(self, http):
        self.http, self._cache, self._lock = http, {}, RLock()
        self._cooldown_until, self._next_request = 0.0, 0.0
        self._spacing = 1
        self._last_start = float("-inf")

    async def read(self, url):
        if not public_url(url):
            raise ProviderFailure("invalid_public_url")
        robots = await self._fetch(ROOT + "/robots.txt", 3600)
        policy = RobotFileParser()
        policy.parse(robots.data.splitlines())
        if not robots_allowed(robots.data, url):
            raise ProviderFailure("robots_disallowed")
        delay = policy.crawl_delay(AGENT) or policy.crawl_delay("*") or 1
        if delay > 30:
            raise ProviderFailure("crawl_delay_exceeds_request_budget")
        self._spacing = max(1, delay)
        with self._lock:
            self._next_request = max(self._next_request, self._last_start + self._spacing)
        return await self._fetch(url.split("#")[0], self.http.ttl)

    async def _fetch(self, url, ttl):
        with http_call("GET", url) as call:
            doc = await self._fetch_scoped(url, ttl)
            call["cache"] = "hit" if doc.cached else "miss"
            return doc

    async def _fetch_scoped(self, url, ttl):
        scope, refresh = cache_context()
        key = (scope, url)
        with self._lock:
            entry = self._cache.get(key)
            if entry and entry[0] > self.http.clock() and not refresh:
                return Document(entry[1].data, entry[1].fetched_at, True)
            if self._cooldown_until > self.http.clock():
                raise ProviderFailure("rate_limited", int(self._cooldown_until - self.http.clock()) + 1)
            delay = max(0, self._next_request - self.http.clock())
            self._last_start = self.http.clock() + delay
            self._next_request = self.http.clock() + delay + self._spacing
        if delay:
            await self.http.sleep(delay)
        async with httpx.AsyncClient(timeout=self.http.timeout, transport=self.http.transport,
                                     follow_redirects=False, headers={"User-Agent": AGENT}) as client:
            for attempt in range(self.http.retries + 1):
                try:
                    if current.get():
                        current.get().check()
                    http_attempt()
                    response = await client.get(url)
                except httpx.RequestError:
                    if attempt < self.http.retries:
                        await self.http.sleep(max(self._spacing, 0.5 * 2 ** attempt))
                        continue
                    raise ProviderFailure("network_error") from None
                http_status(response.status_code)
                if response.status_code in {401, 403}:
                    raise ProviderFailure("public_access_restricted")
                if response.status_code == 429:
                    wait = self.http.retry_delay(response.headers.get("Retry-After"))
                    with self._lock:
                        self._cooldown_until = self.http.clock() + wait
                    raise ProviderFailure("rate_limited", wait)
                if response.status_code in {500, 502, 503, 504} and attempt < self.http.retries:
                    await self.http.sleep(max(self._spacing, 0.5 * 2 ** attempt))
                    continue
                if response.status_code != 200:
                    raise ProviderFailure("public_page_unavailable")
                if len(response.content) > 2_000_000:
                    raise ProviderFailure("invalid_response")
                expected = "text/" if url.endswith("robots.txt") else "text/html"
                if expected not in response.headers.get("content-type", "").lower():
                    raise ProviderFailure("invalid_response")
                doc = Document(response.text, utcnow())
                with self._lock:
                    self._cache[key] = (self.http.clock() + ttl, doc)
                    if len(self._cache) > 128:
                        del self._cache[next(iter(self._cache))]
                return doc

    def discard(self):
        with self._lock:
            scope, _ = cache_context()
            if scope is None:
                self._cache.clear()
            else:
                for key in list(self._cache):
                    if key[0] == scope:
                        del self._cache[key]
