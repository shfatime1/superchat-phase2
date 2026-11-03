"""Async GET transport with bounded TTL caching, retries and rate-limit cooldowns.

Clients are scoped to a fetch so the synchronous chat bridge can use separate
event loops safely. No URLs, payloads or exception text are logged.
"""

import asyncio
from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from threading import RLock
import time

import httpx

from app.providers.models import utcnow


class ProviderFailure(Exception):
    def __init__(self, code, retry_after=None):
        super().__init__(code)
        self.code, self.retry_after = code, retry_after


@dataclass
class Document:
    data: object
    fetched_at: datetime
    cached: bool = False


class ProviderHTTP:
    def __init__(self, timeout=8.0, retries=2, ttl=300, capacity=256, transport=None,
                 clock=time.monotonic, sleep=asyncio.sleep):
        self.timeout, self.retries, self.ttl, self.capacity = timeout, retries, ttl, capacity
        self.transport, self.clock, self.sleep = transport, clock, sleep
        self._cache, self._cooldown, self._lock = OrderedDict(), {}, RLock()

    @staticmethod
    def retry_delay(value):
        try:
            return max(1, min(3600, int(value)))
        except (ValueError, TypeError):
            try:
                return max(1, min(3600, int((parsedate_to_datetime(value) - utcnow()).total_seconds())))
            except (ValueError, TypeError, OverflowError):
                return 30

    async def get(self, url, *, params=None, headers=None, ttl=None):
        # Headers participate in isolation, but credentials are never returned or logged.
        key = (url, str(httpx.QueryParams(params)), tuple(sorted((headers or {}).items())))
        host = httpx.URL(url).host
        with self._lock:
            entry = self._cache.get(key)
            if entry and entry[0] > self.clock():
                self._cache.move_to_end(key)
                return Document(deepcopy(entry[1].data), entry[1].fetched_at, True)
            if entry:
                del self._cache[key]
            if self._cooldown.get(host, 0) > self.clock():
                raise ProviderFailure("rate_limited", int(self._cooldown[host] - self.clock()) + 1)
        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport,
                                     follow_redirects=False) as client:
            for attempt in range(self.retries + 1):
                try:
                    response = await client.get(url, params=params, headers=headers)
                except httpx.RequestError:
                    if attempt < self.retries:
                        await self.sleep(0.25 * 2 ** attempt)
                        continue
                    raise ProviderFailure("network_error") from None
                if response.status_code == 429:
                    delay = self.retry_delay(response.headers.get("Retry-After"))
                    with self._lock:
                        self._cooldown[host] = self.clock() + delay
                    raise ProviderFailure("rate_limited", delay)
                if response.status_code in {408, 500, 502, 503, 504} and attempt < self.retries:
                    await self.sleep(0.25 * 2 ** attempt)
                    continue
                if response.status_code in {401, 403}:
                    raise ProviderFailure("credentials_or_permissions")
                if response.status_code != 200:
                    raise ProviderFailure("upstream_error")
                try:
                    data = response.json()
                except ValueError:
                    raise ProviderFailure("invalid_response") from None
                # Provider error envelopes must never be cached as success.
                if isinstance(data, dict) and (data.get("success") is False or data.get("errors")):
                    raise ProviderFailure("upstream_error")
                doc = Document(data, utcnow())
                with self._lock:
                    self._cache[key] = (self.clock() + (self.ttl if ttl is None else ttl), doc)
                    while len(self._cache) > self.capacity:
                        self._cache.popitem(last=False)
                return Document(deepcopy(data), doc.fetched_at)

    def discard(self):
        """Discard invalid schema payloads; adapters call this on normalization errors."""
        with self._lock:
            self._cache.clear()
