# Phase 2 provider research

Reviewed and rechecked 2026-11-03. Documented APIs are distinguished from verified public-page
access. CinemaPlus public HTML was fetched directly and parsed successfully; no private
endpoints, authentication bypass or ticket/seat APIs were used. Automated tests are offline.

## Aviasales

The official [Travelpayouts Data API documentation](https://support.travelpayouts.com/hc/en-us/articles/203956163-Aviasales-Data-API)
documents `GET https://api.travelpayouts.com/aviasales/v3/prices_for_dates`, `X-Access-Token`
authentication, city/airport IATA origin/destination, departure/return date, currency,
market, direct/one-way flags, sorting and pagination. It returns cached user search fares,
not real-time search or bookable inventory. Empty results do not establish that no flights
or seats exist. The method documentation describes fares found in the last 48 hours.

Official [autocomplete documentation](https://support.travelpayouts.com/hc/en-us/articles/360002322572-Autocomplete-API-for-countries-cities-and-airports-by-Aviasales)
documents `https://autocomplete.travelpayouts.com/places2`. The implementation accepts
explicit three-letter codes and resolves exact city/airport names conservatively. Ambiguous
names require explicit IATA codes. City codes may cover multiple airports; returned airport
codes remain separate. No invented local mapping is used.

Seats, baggage, cabin, arrival times and reservations are not inferred. Credentials and
account permissions need validation in the user's environment. Upstream support for a
requested currency/market is checked through the API response, not assumed conversion.

## Birmarket Azerbaijan

**Public-page follow-up, 2026-11-03:** anonymous HTTP reads now verified 24 product
records with AZN prices, brands, images and official links in a category's HTML, plus
an individual Product page. Robots blocks keyword-search routes and most query strings.
The current consumer terms were inspected; permission for external catalog/image reuse
remains unverified. No active adapter was changed. See the
[public access investigation](birmarket_public_access.md) for exact findings and limits.

Reviewed the official [consumer platform](https://birmarket.az/),
[business platform](https://business.birmarket.az/) and
[knowledge base](https://edu.business.umico.az/). The
[seller agreement](https://edu.business.umico.az/space/knowledge/872513537) describes the
seller's authenticated personal account and mentions API integration. This concerns
merchant goods/orders and does not establish third-party access to the entire consumer
catalog or permission to republish data.

The reviewed public material did not establish an accessible, officially supported public
API contract for product search, categories, details, prices, images or stock. This means
**unverified public access**, not that Birmarket has no APIs. Obtain official integration
documentation, credentials, permitted scopes and data usage rights before implementation.

The adapter reports all catalog capabilities unavailable with `authorization_required`
and links the verified official website. It has no guessed endpoint or implied working token.

`SHOPPING_PROVIDER=ebay` enables the official
[eBay Browse API search](https://developer.ebay.com/develop/api/buy), preserving eBay identity
and native currencies. This does not activate or relabel Birmarket data. `birmarket` remains
an explicit mode for its authorization-only adapter. `auto` now selects BuyWhere, as
documented below. Existing Render variables must be changed manually when applying the upgrade.

eBay requires a developer application with appropriate production Browse API access.
Its documented [client credentials flow](https://developer.ebay.com/develop/guides/sell/authorization)
provides short-lived application tokens. The adapter now mints and renews them from server-side
`EBAY_CLIENT_ID`/`EBAY_CLIENT_SECRET`; a pre-generated `EBAY_ACCESS_TOKEN` is also supported.
No eBay credentials were available locally, so authenticated live eBay calls were not performed.

The documented [inventory discovery/details guide](https://developer.ebay.com/develop/guides/buy/inventory-discovery-and-refresh-guide)
supports retrieving item details after search. Search refinements supply category IDs and
brand/color aspect names; they are not guessed. Native-currency budgets follow the official
[price/priceCurrency filters](https://developer.ebay.com/api-docs/buy/static/ref-buy-browse-filters.html).
Unknown stock is null; only supplied estimated-availability status is displayed. No delivery
or final checkout total is inferred. Production access/quotas must be verified for the user's
account; a free unrestricted Birmarket feed is not established by merchant API availability.

## BuyWhere: active free Shopping source

The [official quickstart](https://buywhere.ai/quickstart),
[API contract](https://api.buywhere.ai/openapi.json) and
[terms](https://buywhere.ai/terms) describe a product-catalog API intended for shopping
applications. The public search operation explicitly has `security: []` and permits
anonymous requests. No account, API key, retailer scraping or restricted route is needed
for SuperChat's default search. Terms prohibit bulk replication and reselling API access;
this integration exposes bounded shopping results, not a raw API proxy or bulk export.

Anonymous live checks on 2026-11-03 returned laptop offers from Newegg, general/outdoor
products from multiple retailers, and headphones with native USD/SGD prices, image URLs
and retailer links. The adapter smoke check returned 50 products within a USD budget,
then verified saved Details and a local cache hit. Some advertised prices were several
months old; missing price dates were also observed. Retrieval time is therefore kept
separate from `price_as_of`, with stale/unknown price-date labels in chat and cards.

Search is scoped with the configured catalog market, and uses documented native-currency
bounds. Application-side checks reject mismatched currencies and out-of-budget prices.
`local`, `unavailable` and `unknown` delivery-ranking flags are not interpreted as stock.
No Azerbaijan delivery, inventory or checkout guarantee is made. Category/brand filtering
and price sorting apply only to returned records; all searches report partial coverage.

The contract marks product-detail/category endpoints as authenticated. Although an initial
read-only detail probe returned HTTP 200, the implementation does not rely on that
incidental anonymous access. Without an optional authorized `BUYWHERE_API_KEY`, Details
and Compare use saved search facts and no authenticated routes are requested. The live
verification script follows the published security requirements as well.

BuyWhere's quota descriptions vary across its onboarding pages; anonymous rate limits
should not be treated as unlimited or guaranteed. HTTP 429 and Retry-After are honored.
The app does not provision accounts/keys or enroll in a paid plan. Affiliate redirects
returned by the API are preserved and disclosed. Official retailer URLs are retained as
a fallback when no valid tracked link is supplied; merchant pages are never fetched by
the backend. No Birmarket labels are attached to these offers.

AS-Mart was also checked because its documentation explicitly supports external catalog
display; its documented versioned search URLs returned HTTP 404 during direct checks,
so it was not integrated. Cancork was rejected for limited coverage and all Cancork
research code was removed at the user's request. The active provider never uses mock
JSON, captured research files, Google Custom Search, Wildmart or these rejected sources.

## CinemaPlus Azerbaijan

The official [CinemaPlus / CineMastercard site](https://cinemastercard.az/),
[FAQ](https://cinemastercard.az/en/faq/) and
[About page](https://web.cinemastercard.az/en/about) identify the Azerbaijan chain and its
consumer schedule/ticket flow. The About page identifies Cinema Plus LLC and explains
that seats/prices are viewed after selecting a showing. This is unrelated to CinemaPlus.com
in Nevada; its documentation was excluded.

### Verified public HTML access

No documented public API or authorized partner feed was found. However, the earlier
API-only limitation was too broad: **the official public HTML itself contains useful facts**.
Direct, unauthenticated HTTP GETs returned 200 for:

- [English movie listings](https://cinemastercard.az/en/).
- [The film “44” and its published schedule](https://cinemastercard.az/en/films/44/).
- [Ganjlik Mall and its published schedule](https://cinemastercard.az/en/cinema/about-cinemaplus/ganjlik-mall/).

The fetched homepage contained 16 listed films. The fetched “44” page contained 142 dated
rows across eight cinemas for November 3–4, 2026. The completed adapter was then checked live
with a November 3 filter and returned one movie, 74 dated sessions and eight cinemas. These
are observations from that fetch, not a static production catalog or a promise about future dates.

The site's [robots.txt](https://cinemastercard.az/robots.txt), fetched directly with HTTP 200,
published these directives:

```text
User-agent: *
Disallow: /*.php
Disallow: /*.log
Disallow: /index.html
Allow: /index.php
Allow: /$
```

The implemented reader uses the permitted pretty HTML routes, not script endpoints. It
rechecks robots at runtime, identifies itself as SuperChat, caches requests, spaces them
by at least one second, bounds page reads and stops on restrictions or unexpected markup.
It does not execute website scripts, reuse sessions/tokens, call internal AJAX, access seat
maps, automate checkout or work around 401/403/rate limits. Source errors may trigger the
explicitly labeled TMDB fallback; a valid empty official search does not.

The published [cinema rules](https://cinemastercard.az/ru/rules/) reviewed through the web
research tool address attendance and ticket terms. No rule specifically granting a public
catalog API, partner feed or bulk data redistribution license was found. The English and
Azerbaijani rules pages intermittently returned 500 during research; a direct Russian-page
request also returned 500 although its content was available to the research tool. **Robots
permission is a crawl directive, not a contractual redistribution license.** A formal feed,
commercial reuse agreement or booking integration still requires the cinema operator's terms
and approval. The implementation only reads public factual listings and links users to source.

### What the public reader returns

| Feature | Verified method | Limit |
| --- | --- | --- |
| Movies | Homepage `.today_list .sortable_movie_home` with observed official film links | Includes presales; a homepage card alone does not confirm a dated showing |
| Posters, age, listed audio languages | Values already published in those cards | Missing values stay unknown |
| Cinema locations | Observed official cinema-name/page links | Street addresses are not inferred; one Ganjlik contact block visibly repeated a 28 Mall address |
| Showtimes | Public film/cinema table rows with explicit `data-date`, time, cinema and hall | Only dates actually present in the HTML; no private requests to force later dates |
| Listed prices | Visible AZN price in the same dated row | Not a final checkout price or seat-category guarantee |
| Film facts | Published runtime, genre and age in the film details section | Full copyrighted synopses are left on the source page |
| Movie/schedule URLs | Actual public anchor hrefs | No standalone per-session URL was verified; `direct_showtime_url` stays null |
| Seats/reservations | Not accessed | Requires an official authorized booking/inventory integration; chat does not reserve |

The raw research HTML lives only under ignored `artifacts/`; production fetches external
pages and never uses those files as data. `scripts/inspect_cinemaplus_public.py` reproduces
the small public-page access audit, and `--verify-provider` exercises the completed reader.

### Secondary metadata fallback

`CINEMA_PROVIDER=auto` prioritizes the public CinemaPlus source. `cinemaplus` disables the
metadata fallback; `tmdb` is an explicit metadata-only choice. The separate fallback uses
official TMDB [search](https://developer.themoviedb.org/reference/search-movie),
[discovery](https://developer.themoviedb.org/reference/discover-movie), movie details and
[application bearer authentication](https://developer.themoviedb.org/docs/authentication-application).
TMDB supplies metadata, not CinemaPlus listings, prices, seats or reservations. Every **TMDB**
movie has `confirmed_cinemaplus_screening=false`; its `cinemas`/`showtimes` remain empty and
`screening_status=unavailable`. Official CinemaPlus movies can set the flag true only when
an actual matching dated public showtime row was parsed.

Follow TMDB's [licensing/attribution requirements](https://developer.themoviedb.org/docs/faq)
and official [image URL construction](https://developer.themoviedb.org/docs/image-basics).
