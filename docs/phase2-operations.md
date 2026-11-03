# Streaming and Phase 2 operations

The frontend uses `POST /api/chat/stream` (SSE over fetch). The JSON endpoint stays
compatible. Events are `progress`, `text`, `complete`, and sanitized `error`;
five-second comment heartbeats keep idle connections observable. Routing happens
first, then each provider result is rendered and streamed immediately as grounded
text. Gemini still chooses the final structured response plan. Raw model reasoning
and unvalidated model text are never streamed. Only `complete` confirms a committed
turn; a partial text event is not a transaction confirmation.

Streaming requires `request_id`. JSON and SSE share the same ownership checks,
session locks and request-ID replay ledger. A disconnect does not rerun or cancel
an already started operation: the bounded worker finishes, and the same request ID
recovers its result. The client keeps pending IDs, uses a 45-second idle timer and
a 180-second ceiling, and does not discard messages after an interrupted stream.
Provider and Gemini timeouts still bound individual calls; the default 120-second
request budget is checked at safe stage/call boundaries and rolls back an expired
turn. SSE buffering is disabled with `X-Accel-Buffering: no`.

Provider results default to a 30-minute TTL in both JSON and Cinema HTML caches.
Cache keys include conversation identity, endpoint, canonical request parameters,
and authentication headers. Changed currency, filters, date, market, page or
credentials cannot reuse an incompatible response. Errors/malformed envelopes are
not cached; malformed-response invalidation is scoped to the active conversation.
`refresh_cache: true` bypasses applicable cache entries, including routing cache.
Independent fresh searches can reuse their routing for 30 minutes; contextual
follow-ups, selections and mutations always route again. Relative-date routing
cache keys include the Baku date. Caches are bounded and clear on process restart.

The Debugger button below each assistant turn opens a right drawer. Saved
diagnostics contain only an opaque trace ID, source/category/domain/operation and
parameter **names**, safe endpoint templates, timings, attempts, HTTP statuses,
cache hits/misses and allowlisted error codes. They contain no prompts, parameter
values, cookies, authorization headers, API keys, exception bodies or reasoning.
Old saved turns show a no-diagnostics notice. Audit logs contain trace IDs, total
duration and provider-call counts, with no raw request/response bodies.

Authentication remains anonymous, browser-owned sessions (HttpOnly SameSite cookie),
not account login. Someone with another browser's session ID cannot read its history,
diagnostics or stream. Provider credentials remain environment-only and server-side;
401/403 are sanitized. eBay retains automatic OAuth token renewal. Upstream 429
responses honor bounded `Retry-After` cooldowns, with bounded timeout/5xx retries.
Application limits cover JSON and SSE: 30 new requests/browser/minute and 120/IP/minute
by default; completed request-ID replays do not consume another request. Eight
streaming workers bound concurrent work. These are process-local controls: continue
using one worker/instance, or introduce a shared store before scaling horizontally.

BuyWhere/eBay pagination uses validated offsets in increments of 50 (maximum 9950).
The UI offers **Load more products** when a provider reports another page. It never
follows arbitrary provider-returned URLs. Empty pages terminate pagination; changing
constraints resets the page. Earlier carousel results remain in conversation history.
Flight/Cinema coverage remains bounded and honestly marked partial; no undocumented
pagination or private cinema routes were added.

For an existing Render service, change an existing `PROVIDER_CACHE_TTL=300` override
to `1800` when you next deploy. No `.env` file is required. No deployment was performed.

Focused verification: `python -m pytest tests/test_phase2_ops.py -q` and
`node --test tests/stream.test.cjs`. Existing provider authentication, cooldown,
timeout and session-replay regressions are also reused.
