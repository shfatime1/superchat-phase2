"""Server-side eBay application tokens with expiry renewal and safe failures."""

import base64
import asyncio
from threading import Event, RLock

import httpx

from app.providers.http import ProviderFailure

TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"


class EbayCredentials:
    def __init__(self, http, token=None, client_id=None, client_secret=None):
        self.http, self.static_token = http, token
        self.client_id, self.client_secret = client_id, client_secret
        self._token, self._expiry, self._cooldown = None, 0.0, 0.0
        self._lock = RLock()
        self._minting, self._ready = False, Event()

    @property
    def configured(self):
        return bool(self.static_token or self.client_id and self.client_secret)

    def invalidate(self):
        with self._lock:
            self._token, self._expiry = None, 0.0

    async def token(self):
        if self.static_token:
            return self.static_token
        with self._lock:
            if self._token and self.http.clock() < self._expiry:
                return self._token
            if self.http.clock() < self._cooldown:
                raise ProviderFailure("rate_limited", int(self._cooldown - self.http.clock()) + 1)
            wait = self._minting
            if not wait:
                self._minting = True
                self._ready.clear()
        if wait:
            await asyncio.to_thread(self._ready.wait)
            return await self.token()
        try:
            return await self._mint()
        finally:
            with self._lock:
                self._minting = False
                self._ready.set()

    async def _mint(self):
        if not self.client_id or not self.client_secret:
            raise ProviderFailure("missing_credentials")
        basic = base64.b64encode((self.client_id + ":" + self.client_secret).encode()).decode()
        async with httpx.AsyncClient(timeout=self.http.timeout, transport=self.http.transport, follow_redirects=False) as client:
            for attempt in range(self.http.retries + 1):
                try:
                    response = await client.post(TOKEN_URL, headers={"Authorization": "Basic " + basic},
                        data={"grant_type": "client_credentials", "scope": "https://api.ebay.com/oauth/api_scope"})
                except httpx.RequestError:
                    if attempt < self.http.retries:
                        await self.http.sleep(0.25 * 2 ** attempt)
                        continue
                    raise ProviderFailure("network_error") from None
                if response.status_code == 429:
                    delay = self.http.retry_delay(response.headers.get("Retry-After"))
                    with self._lock:
                        self._cooldown = self.http.clock() + delay
                    raise ProviderFailure("rate_limited", delay)
                if response.status_code in {500, 502, 503, 504} and attempt < self.http.retries:
                    await self.http.sleep(0.25 * 2 ** attempt)
                    continue
                if response.status_code in {400, 401, 403}:
                    raise ProviderFailure("credentials_or_permissions")
                if response.status_code != 200:
                    raise ProviderFailure("upstream_error")
                try:
                    payload = response.json()
                    token, lifetime = payload["access_token"], payload["expires_in"]
                    if not isinstance(token, str) or not token or type(lifetime) is not int or lifetime <= 0:
                        raise ValueError("Invalid token")
                except (ValueError, KeyError, TypeError):
                    raise ProviderFailure("invalid_response") from None
                with self._lock:
                    self._token = token
                    self._expiry = self.http.clock() + lifetime - min(60, lifetime / 10)
                return token
