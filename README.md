# SuperChat — Phase 2

FastAPI chat with Gemini routing, conversation history and independent flight, shopping
and cinema state. Production uses external provider adapters. No deployment has been
performed. Bonus features remain out of scope.

## Provider coverage

| Service | Implemented | Limits |
| --- | --- | --- |
| Aviasales / Travelpayouts | Official Data API fares by origin/destination/date, return date, IATA/city resolution, currency, supported filters, sorting and comparisons | Cached search prices, **not live quotes**. No seats, baggage, cabin, group inventory or reservations. |
| Birmarket Azerbaijan | Provider adapter, capability/status reporting, official website handoff | Public catalog API access was not verified. Search, categories, details, prices, images and stock require authorized documentation/access. |
| CinemaPlus Azerbaijan / CineMastercard | Official website handoff and screening capability reporting | No authorized public API was verified for current movies, cinemas, showtimes, prices, seats or film details. |
| TMDB (optional) | Movie search/discovery and details, genres, ratings, runtime when provided, poster URLs | Metadata only; **never confirmed CinemaPlus screenings**. |
| eBay (optional) | Official Browse API keyword search, provider price sorting, images/links and native currencies | Clearly labeled eBay, never Birmarket. Stock, delivery to Azerbaijan, taxes and checkout totals are unverified. Requires authorized production OAuth access. |

See [research and official sources](docs/provider_research.md) for the distinction between
seller API access and public consumer catalog access. No undocumented endpoints or
scraping are used. No results are fabricated.

## Run without a `.env` file

Python 3.12 is supported. In PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:GEMINI_API_KEY = "your-gemini-key"
$env:TRAVELPAYOUTS_API_TOKEN = "your-travelpayouts-token"
# Optional movie metadata:
$env:TMDB_READ_ACCESS_TOKEN = "your-tmdb-api-read-access-token"
python -m app.serve
```

Open http://localhost:8000. `.env.example` documents configuration; using a local `.env`
is optional. Existing environment variables take precedence. Secrets stay server-side
and are omitted from settings repr, responses and logs.

## Configuration

| Environment variable | Default / purpose |
| --- | --- |
| `GEMINI_API_KEY` | Gemini routing and grounded response planning |
| `GEMINI_MODEL` | `gemini-flash-latest` |
| `SUPERCHAT_ROUTING_MODE` | `auto`: Gemini with conservative local fallback; `strict`: Gemini required; `offline`: local routing |
| `SUPERCHAT_DATA_MODE` | `providers`; explicit `fixtures` for development/testing only |
| `TRAVELPAYOUTS_API_TOKEN` | Official Aviasales Data API token; sent in `X-Access-Token` |
| `FLIGHT_CURRENCY` | `AZN`; request `currency` overrides it; no invented exchange rates |
| `FLIGHT_MARKET` | Optional documented market code; blank uses provider default |
| `TMDB_READ_ACCESS_TOKEN` | Optional TMDB application Read Access Token, enabling metadata fallback |
| `SHOPPING_PROVIDER` | `birmarket`; deliberately set `ebay` to select the separate alternative |
| `EBAY_ACCESS_TOKEN` | Optional eBay production OAuth application access token; rotate/renew externally |
| `EBAY_MARKETPLACE` | `EBAY_US` |
| `PROVIDER_TIMEOUT_SECONDS` | `8`, bounded to 0.1–30 seconds per HTTP phase |
| `PROVIDER_RETRIES` | `2`, bounded to 0–3 retries for transport errors and selected transient HTTP statuses |
| `PROVIDER_CACHE_TTL` | `300` seconds, bounded to 1–86400; IATA lookups cache for one day |
| `GEMINI_TIMEOUT_MS` / `GEMINI_RESPONSE_TIMEOUT_MS` | `30000` / `4000` |
| `COOKIE_SECURE` | `false` locally; `true` on Render HTTPS |
| `PORT` / `HOST` | `8000` / `0.0.0.0`; Render supplies `PORT` |

Local fallback supports a smaller set of English requests; Gemini handles richer intent
extraction. Provider mode uses the current Asia/Baku date. Fixture mode retains the
original 2026-11-02 reference date.

## NEW Render Web Service

Create a new Python Web Service from this repository; do not reuse the Phase 1 service.
`render.yaml` also provides a Blueprint configuration. No deployment is performed here.

1. Build: `pip install -r requirements.txt`.
2. Start: `python -m app.serve`.
3. Health check: `/health`.
4. Set `GEMINI_API_KEY` and `TRAVELPAYOUTS_API_TOKEN` directly in Render Environment
   Variables, with `COOKIE_SECURE=true`, `SUPERCHAT_DATA_MODE=providers` and
   `SUPERCHAT_ROUTING_MODE=auto` (or `strict`).
5. Optionally add `TMDB_READ_ACCESS_TOKEN`. Keep `SHOPPING_PROVIDER=birmarket` unless
   deliberately enabling eBay with its own authorized token.

`GET /health` checks application initialization independently of optional credentials and
external outages. `GET /api/providers` reports configuration/capabilities without external
requests. Actual chat results report provider status/errors. Configuration does not prove
a successful authenticated connection.

Use one worker and one service instance. Sessions, request idempotency, rate-limit cooldowns
and caches are process-local. Restarts clear server context; browser history remains readable.
Horizontal scaling requires shared persistence and coordination.

## Architecture and data semantics

`app/providers/` separates clients, normalized schemas and async HTTP transport. A synchronous
bridge runs provider calls in FastAPI's worker thread, preserving the existing per-session
transactions. Retries are bounded, errors sanitized, and caches have TTL/capacity bounds.
HTTP 429 honors `Retry-After` through a host cooldown rather than blocking a thread for
long sleeps. Expired data is not served as an outage fallback.

The existing `DomainResult` and `data.flights/products/movies` containers are retained.
Provider rows use `price.amount` and `price.currency`; the frontend handles both provider
rows and historical fixture rows. `data.provider` exposes `live`, `cached` or `unavailable`,
source, retrieval timestamp and local cache use. `data.provider_error` carries a safe
error code/message and optional retry delay. Null means unknown.

Aviasales is always `cached`, even immediately after HTTP success, because the upstream
API returns cached search fares. One-way date grouping may return only one offer. Searches
request the first 100 records; local filters/comparisons apply to returned offers, not every
flight. Unsupported baggage/cabin filters fail explicitly. AZN budgets cannot filter non-AZN
prices. Airline filters accept provider IATA codes. Time filters use the provider timestamp's
clock time/offset. Passenger counts do not verify inventory or group totals.

TMDB/eBay use `live` for fresh successful retrieval and `cached` for local cache hits. This
does not imply live inventory. Movie discovery is generic TMDB discovery; date/location/ticket
constraints cannot confirm CinemaPlus screenings. Comparisons/session details are labeled
cached with original retrieval time. Explicit new searches replace selection snapshots even
when empty/unavailable.

No active provider path reads `data/*.json`. Original JSON and mock domain services remain
only for explicit `SUPERCHAT_DATA_MODE=fixtures`. They are never an API failure fallback.
Fixture mode retains the original demonstration operations.

## Testing

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Provider tests use `httpx.MockTransport`, placeholder credentials and no live API calls.
They cover all three domain adapters, optional eBay, IATA ambiguity, currency/filters,
cache expiry, retries/timeouts/rate limits, malformed data, authorization boundaries,
metadata separation, comparisons/state/history and startup without fixtures. Existing
regression tests explicitly select fixture mode.

Optional desktop/mobile browser QA: `python -m scripts.provider_browser_smoke` (requires
Microsoft Edge and `requirements-dev.txt`). It uses local provider stubs and saves
`docs/screenshots/phase2-*.png`; those screenshots illustrate UI behavior, not live results.

## TMDB attribution

This product uses the TMDB API but is not endorsed or certified by TMDB. Attribution appears
in the app's About dialog. Follow [TMDB's rules](https://developer.themoviedb.org/docs/faq).
The About dialog links the official TMDB logo asset without altering its artwork. The developer
API is for noncommercial use; obtain the relevant commercial license for revenue-generating use.

Existing Phase 1 reports/screenshots in `docs/` are historical fixture demonstrations.
