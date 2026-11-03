# Phase 2 provider research

Reviewed 2026-11-03. Documented capabilities are distinguished from access verified for this
project. No private endpoints were called and no catalog/showtime scraping was implemented.
Automated tests do not perform live authenticated provider calls.

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

Explicit `SHOPPING_PROVIDER=ebay` enables the official
[eBay Browse API search](https://developer.ebay.com/develop/api/buy), preserving eBay identity
and native currencies. Production bearer tokens require appropriate API access/approval;
renewal is managed externally. Birmarket remains the default.

## CinemaPlus Azerbaijan

The official [CinemaPlus / CineMastercard site](https://cinemastercard.az/),
[FAQ](https://cinemastercard.az/en/faq/) and
[About page](https://web.cinemastercard.az/en/about) identify the Azerbaijan chain and its
consumer schedule/ticket flow. The About page identifies Cinema Plus LLC and explains
that seats/prices are viewed after selecting a showing. This is unrelated to CinemaPlus.com
in Nevada; its documentation was excluded.

No accessible authorized public API contract for current movies, cinema locations, showtimes,
ticket prices, seats or film details was verified. Public consumer pages do not authorize
private endpoint access or automated extraction. Obtain an official partner API/feed contract
before adding these capabilities. Until then they remain explicitly unavailable in chat.

The separate fallback uses official TMDB [search](https://developer.themoviedb.org/reference/search-movie),
[discovery](https://developer.themoviedb.org/reference/discover-movie), movie details and
[application bearer authentication](https://developer.themoviedb.org/docs/authentication-application).
TMDB supplies metadata, not CinemaPlus listings, prices, seats or reservations. Every movie
has `confirmed_cinemaplus_screening=false`; `cinemas`/`showtimes` remain empty and
`screening_status=unavailable`.

Follow TMDB's [licensing/attribution requirements](https://developer.themoviedb.org/docs/faq)
and official [image URL construction](https://developer.themoviedb.org/docs/image-basics).
