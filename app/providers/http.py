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
from app.diagnostics import cache_context, current, active_call, http_call, http_status, http_attempt
from app.providers.network import Attempt, network_failure


class ProviderFailure(Exception):
    def __init__(self, code, retry_after=None, reason=None):
        super().__init__(code)
        self.code, self.retry_after = code, retry_after
        self.reason = reason


@dataclass
class Document:
    data: object
    fetched_at: datetime
    cached: bool = False


def run_provider(coroutine):
    """Close the per-call loop without waiting for a cancelled OS DNS worker.

    asyncio.run waits for its default executor during shutdown, even after a DNS
    future has timed out. Public loop.close shuts that executor down without
    waiting; its already-running resolver finishes normally in the background.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coroutine)
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()


class ProviderHTTP:
    def __init__(self, timeout=8.0, retries=2, ttl=1800, capacity=256, transport=None,
                 clock=time.monotonic, sleep=asyncio.sleep, request_budget=12, connect_timeout=3,
                 domain_budget=20):
        self.timeout, self.retries, self.ttl, self.capacity = timeout, retries, ttl, capacity
        self.transport, self.clock, self.sleep = transport, clock, sleep
        self._cache, self._cooldown, self._lock = OrderedDict(), {}, RLock()
        self.request_budget, self.connect_timeout, self.domain_budget = request_budget, connect_timeout, domain_budget

    async def request(self, url, *, params=None, headers=None, min_spacing=0, before_attempt=None):
        """One wall-clock budget covers DNS, TCP, TLS, body reads AND retries."""
        try:
            return await asyncio.wait_for(self._request(url, params=params, headers=headers,
                min_spacing=min_spacing, before_attempt=before_attempt), self.request_budget)
        except asyncio.TimeoutError:
            raise ProviderFailure("timeout", reason="request_budget_exhausted") from None

    async def run_domain(self, coroutine, domain):
        trace = current.get()
        budget = min(self.domain_budget, getattr(trace, "provider_budget", self.domain_budget))
        try:
            return await asyncio.wait_for(coroutine, budget)
        except asyncio.TimeoutError:
            if trace:
                trace.data["errors"].append({"domain": domain, "code": "timeout", "reason": "domain_budget_exhausted"})
            raise ProviderFailure("timeout", reason="domain_budget_exhausted") from None

    async def _request(self, url, *, params, headers, min_spacing, before_attempt):
        timeout = httpx.Timeout(self.timeout, connect=min(self.timeout, self.connect_timeout),
                                write=min(self.timeout, 3), pool=min(self.timeout, 1))
        # Keep certificate verification and configured environment proxies intact.
        try:
            client = httpx.AsyncClient(timeout=timeout, transport=self.transport, verify=True,
                                       follow_redirects=False)
        except OSError:
            # Missing/unreadable CA bundles and invalid SSL_CERT_FILE/DIR are
            # configuration failures, not provider JSON/layout errors.
            raise ProviderFailure("network_error", reason="tls_configuration_error") from None
        except ValueError:
            raise ProviderFailure("network_error", reason="transport_configuration_error") from None
        async with client:
            for index in range(self.retries + 1):
                if before_attempt:
                    await before_attempt()
                if current.get():
                    current.get().check()
                http_attempt()
                attempt = Attempt(index + 1)
                try:
                    response = await client.get(url, params=params, headers=headers,
                                                extensions={"trace": attempt.trace})
                except httpx.RequestError as exc:
                    reason, retryable = network_failure(exc, attempt.data["stage"])
                    attempt.finish(reason=reason, retryable=retryable)
                    if retryable and index < self.retries:
                        delay = max(min_spacing, 0.25 * 2 ** index)
                        attempt.data["retry_delay_ms"] = round(delay * 1000)
                        await self.sleep(delay)
                        continue
                    raise ProviderFailure("timeout" if isinstance(exc, httpx.TimeoutException) else "network_error",
                                          reason=reason) from None
                except asyncio.CancelledError:
                    attempt.finish(reason="budget_cancelled", retryable=False)
                    raise
                http_status(response.status_code)
                attempt.finish(status=response.status_code)
                call = active_call.get()
                if call is not None:
                    kind = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                    call["response_type"] = kind if kind in {"application/json", "text/html", "text/plain"} else "other"
                if response.status_code in {408, 500, 502, 503, 504} and index < self.retries:
                    delay = max(min_spacing, 0.25 * 2 ** index)
                    attempt.data["retry_delay_ms"] = round(delay * 1000)
                    await self.sleep(delay)
                    continue
                return response

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
        with http_call("GET", url) as call:
            doc = await self._get(url, params=params, headers=headers, ttl=ttl)
            call["cache"] = "hit" if doc.cached else "miss"
            return doc

    async def _get(self, url, *, params=None, headers=None, ttl=None):
        # Headers participate in isolation, but credentials are never returned or logged.
        scope, refresh = cache_context()
        key = (scope, url, str(httpx.QueryParams(sorted(httpx.QueryParams(params).multi_items()))), tuple(sorted((headers or {}).items())))
        host = httpx.URL(url).host
        with self._lock:
            entry = self._cache.get(key)
            if entry and entry[0] > self.clock() and not refresh:
                self._cache.move_to_end(key)
                return Document(deepcopy(entry[1].data), entry[1].fetched_at, True)
            if entry:
                del self._cache[key]
            if self._cooldown.get(host, 0) > self.clock():
                raise ProviderFailure("rate_limited", int(self._cooldown[host] - self.clock()) + 1)
        response = await self.request(url, params=params, headers=headers)
        if response.status_code == 429:
            delay = self.retry_delay(response.headers.get("Retry-After"))
            with self._lock:
                self._cooldown[host] = self.clock() + delay
            raise ProviderFailure("rate_limited", delay)
        if response.status_code in {401, 403}:
            raise ProviderFailure("credentials_or_permissions")
        if response.status_code != 200:
            raise ProviderFailure("upstream_error")
        try:
            data = response.json()
        except ValueError:
            raise ProviderFailure("invalid_response", reason="invalid_json") from None
        # Provider error envelopes must never be cached as success.
        if isinstance(data, dict) and (data.get("success") is False or data.get("errors")):
            raise ProviderFailure("upstream_error")
        doc = Document(data, utcnow())
        with self._lock:
            self._cache[key] = (self.clock() + (self.ttl if ttl is None else ttl), doc)
            while len(self._cache) > self.capacity:
                self._cache.popitem(last=False)
        return Document(deepcopy(data), doc.fetched_at)

    def discard(self, host=None):
        """Discard invalid schema payloads; adapters call this on normalization errors."""
        with self._lock:
            scope, _ = cache_context()
            for key in list(self._cache):
                if (scope is None or key[0] == scope) and (host is None or httpx.URL(key[1]).host == host):
                    del self._cache[key]
