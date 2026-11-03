# SuperChat — Phase 2

FastAPI chat with Gemini routing, conversation history and independent flight, shopping
and cinema state. Production uses external provider adapters. The current Shopping/Cinema
upgrade has not been pushed or deployed. Bonus features remain out of scope.

## Provider coverage

| Service | Implemented | Limits |
| --- | --- | --- |
| Aviasales / Travelpayouts | Official Data API fares by origin/destination/date, return date, IATA/city resolution, currency, supported filters, sorting and comparisons | Cached search prices, **not live quotes**. No seats, baggage, cabin, group inventory or reservations. |
| Birmarket Azerbaijan | Provider adapter, capability/status reporting, official website handoff | Public catalog API access was not verified. Search, categories, details, prices, images and stock require authorized documentation/access. |
| BuyWhere (default Shopping) | Documented public catalog search for electronics and general goods, native-currency prices, images, retailer links, saved Details/Compare, price/category/reported-brand filtering and local price sorting | Anonymous search was verified without a key. Partial catalog snapshots; some prices are old or have no price date. Stock and Azerbaijan delivery unverified. Affiliate links are disclosed. |
| CinemaPlus Azerbaijan / CineMastercard | **Primary Cinema source:** movies, posters, official movie/schedule links, cinema names/links, dated public showtimes, halls and listed AZN prices; details include runtime, genre and age when published | Reads robots-permitted public HTML, not a documented API. No private endpoints, seat inventory or booking. No invented standalone session URLs. |
| TMDB (secondary) | Metadata search/discovery/details when the official source fails or `CINEMA_PROVIDER=tmdb` is explicitly selected | Clearly labeled metadata; **never confirmed CinemaPlus screenings**. |
| eBay (Shopping fallback) | Official Browse search/details, images/links, native-currency budgets, price sorting, category/brand/color refinements, reported item aspects and estimated availability when supplied | Always labeled eBay, never Birmarket. Requires authorized credentials and production API access. Delivery, taxes and checkout totals are unverified. |

See [research and official sources](docs/provider_research.md) for the distinction between
seller API access and public consumer catalog access. CinemaPlus uses a bounded public-page
reader that honors robots rules and access restrictions. No undocumented private endpoints,
login bypass or seat API calls are used. No results are fabricated.

## Run without a `.env` file

Python 3.12 is supported. In PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:GEMINI_API_KEY = "your-gemini-key"
$env:TRAVELPAYOUTS_API_TOKEN = "your-travelpayouts-token"
# Real shopping: public BuyWhere search needs no key or account.
$env:SHOPPING_PROVIDER = "buywhere"
$env:BUYWHERE_MARKET = "US"
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
| `CINEMA_PROVIDER` | `auto`: official CinemaPlus public pages first, TMDB only on source error if configured; `cinemaplus`: official pages only; `tmdb`: explicit metadata-only mode |
| `SHOPPING_PROVIDER` | `auto` or `buywhere`: public BuyWhere catalog; `ebay`: existing authorized eBay adapter; `birmarket`: authorization-only adapter |
| `BUYWHERE_MARKET` | `US`; supported catalog markets: `US`, `SG`, `VN`, `TH`, `MY`. This is catalog selection, not the user's address or confirmed Azerbaijan delivery. |
| `BUYWHERE_API_KEY` | Optional server-side Bearer key. Not needed for public search or saved Details/Compare. Enables authenticated product-detail refresh. No automatic account/key creation. |
| `EBAY_CLIENT_ID` / `EBAY_CLIENT_SECRET` | Recommended eBay application credentials; OAuth tokens are minted server-side, cached until expiry and renewed automatically |
| `EBAY_ACCESS_TOKEN` | Optional pre-generated token, taking precedence over client credentials; its expiry must be managed externally |
| `EBAY_MARKETPLACE` | `EBAY_US` |
| `PROVIDER_TIMEOUT_SECONDS` | `8`, bounded to 0.1–30 seconds per HTTP phase |
| `PROVIDER_RETRIES` | `2`, bounded to 0–3 retries for transport errors and selected transient HTTP statuses |
| `PROVIDER_CACHE_TTL` | `1800` seconds (30 minutes), bounded to 1–86400; session-isolated; IATA reference lookups cache for one day |
| `CHAT_TIMEOUT_SECONDS` / `CHAT_RATE_LIMIT` | `120` seconds request budget / `30` new requests per browser per minute; IP ceiling is four times the browser limit |
| `GEMINI_TIMEOUT_MS` / `GEMINI_RESPONSE_TIMEOUT_MS` | `30000` / `4000` |
| `COOKIE_SECURE` | `false` locally; `true` on Render HTTPS |
| `PORT` / `HOST` | `8000` / `0.0.0.0`; Render supplies `PORT` |

Gemini handles AZ/EN/RU and mixed-language intent extraction. Local fallback supports
the tested multilingual search/follow-up grammar and clarifies unsupported requests.
Reply language follows the current message or explicit page language preference.
Provider mode uses the current Asia/Baku date. Fixture mode retains the
original 2026-11-02 reference date.

See [multilingual Shopping diagnostics](docs/multilingual-shopping.md) for the verified
BuyWhere nullable-category fix, language behavior, and carousel checks. Discovery cards
initially render seven records; arrows or swiping reveal all remaining returned matches.

See [Phase 2 streaming and operations](docs/phase2-operations.md) for streamed progress,
the sanitized Debugger, 30-minute session caches, authentication boundaries, request
limits, pagination and safe timeout/retry behavior. Existing Render services with an
older `PROVIDER_CACHE_TTL=300` override should use `1800` at the next deployment.

## Update configuration for the existing Render service

The Phase 2 service is already deployed. These local changes have not been deployed or
pushed. When applying the upgrade, retain the working Gemini and Travelpayouts variables.

1. Build: `pip install -r requirements.txt`.
2. Start: `python -m app.serve`.
3. Health check: `/health`.
4. Set `GEMINI_API_KEY` and `TRAVELPAYOUTS_API_TOKEN` directly in Render Environment
   Variables, with `COOKIE_SECURE=true`, `SUPERCHAT_DATA_MODE=providers` and
   `SUPERCHAT_ROUTING_MODE=auto` (or `strict`).
5. Set `CINEMA_PROVIDER=auto`. CinemaPlus public listings require no API token.
6. Set `SHOPPING_PROVIDER=buywhere` and `BUYWHERE_MARKET=US`. Public search needs no
   shopping credentials or approval. Optional `BUYWHERE_API_KEY` enables detail refresh.
   To retain eBay explicitly, set `SHOPPING_PROVIDER=ebay` and its authorized credentials.
7. Optionally retain/add `TMDB_READ_ACCESS_TOKEN` as the secondary metadata fallback.

Changing local defaults or `render.yaml` does not update existing Render Environment Variables.
No local `.env` file is required. `beautifulsoup4` is included in runtime dependencies.

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

CinemaPlus public pages, TMDB, BuyWhere and eBay use `live` for fresh successful retrieval and `cached`
for local cache hits. This describes retrieval, not inventory. CinemaPlus rows retain the
actual published date/time and price. A homepage listing alone does not confirm a dated
screening; only parsed showtime rows set `confirmed_cinemaplus_screening=true`.
TMDB metadata always keeps that flag false and has no CinemaPlus showtimes.

The public CinemaPlus reader fetches only the official `/en/`, observed film/cinema links,
and `robots.txt`. It caches pages for up to 15 minutes and robots for an hour, spaces public
requests by at least one second, bounds broad schedule searches to three film pages, rejects
redirects/unknown paths, and stops on robots denial, 401/403, rate limits or unexpected markup.
Movie/cinema selection yields a focused source page; broad searches remain explicitly partial.
An empty valid official search is not replaced with generic TMDB movies. Street addresses are
left unknown where the public contact block appears shared or cannot be reliably attributed.
The HTML provides film/schedule links but no independently verified per-session booking URL;
`direct_showtime_url` and `seats_available` remain null. Final prices and booking stay on the site.

eBay supports `currency` + `min_price`/`max_price` for native-currency budgets (for example,
"headphones under 50 USD"). AZN-specific budget fields are never applied to USD prices.
Category/brand/color filters use eBay's documented refinements, not guessed IDs. Ignored-filter
warnings become explicit errors. Search-time stock filtering is unsupported; details display
estimated availability only when eBay supplies it. No quantity or delivery promise is inferred.

BuyWhere uses only its documented public `/v1/products/search` API by default. It does
not scrape retailer pages. Its [public search contract](https://api.buywhere.ai/openapi.json)
explicitly permits anonymous calls, and its [terms](https://buywhere.ai/terms) describe
catalog use in shopping applications. Free access has quotas; HTTP 429 honors provider
backoff. Paid plans and bulk data replication are outside this integration.

Try "Show headphones under 100 USD", "Find laptops", or "Find a backpack".
Native price bounds are sent upstream and checked against the actual response currency;
AZN budgets and stock/color filters return explicit unsupported-filter messages. Categories
and brands refine keyword search; explicitly reported mismatching brands are excluded.
Comparisons, relevance filtering and price sorting cover only the first 50 returned
records. They do not establish market-wide absence or a global cheapest offer. Stock remains
unknown: BuyWhere's `local`/`unavailable` delivery ranking is not stock inventory.

Product `price_as_of` is distinct from the retrieval timestamp. Dates older than 24 hours
are marked stale, missing dates stay unknown, and no timestamp or exchange rate is invented.
BuyWhere may earn a commission through tracked retailer links. Without a key, Details/Compare
use the clearly labeled saved search snapshot; authenticated detail/category routes are
never requested. With an optional authorized key, Details can refresh the selected item.

`auto` now selects BuyWhere even if old eBay credentials remain in the environment.
Existing eBay behavior remains available with explicit `SHOPPING_PROVIDER=ebay`.

No active provider path reads `data/*.json`. Original JSON and mock domain services remain
only for explicit `SUPERCHAT_DATA_MODE=fixtures`. They are never an API failure fallback.
Fixture mode retains the original demonstration operations.

## Testing

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Provider tests use `httpx.MockTransport`, placeholder credentials and no live API calls.
They cover all three domain adapters, BuyWhere, optional eBay, IATA ambiguity, currency/filters,
cache expiry, retries/timeouts/rate limits, malformed data, authorization boundaries,
metadata separation, comparisons/state/history and startup without fixtures. Existing
regression tests explicitly select fixture mode.

Optional desktop/mobile browser QA: `python -m scripts.provider_browser_smoke` (requires
Microsoft Edge and `requirements-dev.txt`). It uses local provider stubs and saves
`docs/screenshots/phase2-*.png`; those screenshots illustrate UI behavior, not live results.

`python -m scripts.catalog_browser_smoke` verifies the new CinemaPlus schedule and eBay
image/details cards on desktop/mobile using contract stubs. Its `cinemaplus-*.png` and
`shopping-*.png` screenshots illustrate layout, not live listings.

Optional live read-only CinemaPlus verification:
`python scripts/inspect_cinemaplus_public.py --verify-provider`. This reads robots-permitted
public pages only. It needs network access but no API credentials. Automated tests remain offline.

Optional live Shopping verification: `python scripts/verify_buywhere.py --provider`.
It checks real anonymous product search, native-currency budgets, saved Details and caching.
`python -m scripts.shopping_browser_smoke` checks Shopping cards, images, retailer links,
stale-price labels, Details and Compare on desktop/mobile using offline API contract stubs.

## TMDB attribution

This product uses the TMDB API but is not endorsed or certified by TMDB. Attribution appears
in the app's About dialog. Follow [TMDB's rules](https://developer.themoviedb.org/docs/faq).
The About dialog links the official TMDB logo asset without altering its artwork. The developer
API is for noncommercial use; obtain the relevant commercial license for revenue-generating use.

Existing Phase 1 reports/screenshots in `docs/` are historical fixture demonstrations.
