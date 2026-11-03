# Birmarket public catalog access investigation

Checked 2026-11-03 against the official site with anonymous, read-only requests.
This investigation changes no active provider, routing, frontend or deployment setting.

## Verified public data

The [telephone/accessories category](https://birmarket.az/categories/2-telefonlar-ve-aksessuarlar)
returned HTTP 200 with **24 real product records in its server-rendered HTML**. Its
`application/ld+json` CollectionPage / ItemList contains product IDs, titles, brands,
official product URLs, image URLs, AZN offer prices and advertised availability.
The same product cards are visible in the HTML. No JavaScript execution, login,
merchant credentials or direct calls to undocumented APIs were needed for these records.

An observed [Apple 20W adapter product page](https://birmarket.az/product/450571-shebeke-enerji-toplama-cihazi-apple-20w-usb-c-power-adapter-mhje3-ag)
also returned HTTP 200 with Product structured data. Its published offer was **55.00 AZN**
at inspection. That is a captured advertised price, not a guaranteed checkout quote.
Images are referenced on `strgimgr.umico.az` and, on the product page, `strgimgr.b-cdn.net`.
Image URLs are verified in the public markup; image reuse/hotlinking rights are not established.

The [public sitemap index](https://birmarket.az/sitemap.xml) returned HTTP 200 and links
product, category and brand sitemap indexes. It supplies URL discovery, not a licensed
price/stock feed. No bulk sitemap traversal was performed.

## Access rules

The [live robots.txt](https://birmarket.az/robots.txt) returned HTTP 200. Its wildcard-agent
rules do not disallow the tested plain category or product URLs. They do disallow
`/search/`, `/keyword/`, `/ru/keyword/`, `/en/`, account/cart/authentication routes,
and most query strings. Specific rules allow simple `?page=...` and category
`?view=categories` forms, while additional parameters can make them disallowed again.
Every URL must therefore be evaluated with its **query string**, wildcard matching and
longest-rule precedence. A path-only check is insufficient. Disallowed URLs were not fetched.

The storefront's user-agreement dialog identifies the current
[consumer terms](https://birmarket.az/shopping-public-offer), which returned HTTP 200.
The older `/legal/market_termsofuse` URL linked in the seller agreement returned HTTP 404.

Consumer terms sections 2.2 and 2.4 describe free consumer product discovery and access
to seller-supplied information. Section 4.16 says availability is clarified at order
placement and can change. The reviewed terms did not establish an explicit grant for
an external automated catalog service or redistribution of product images. This is
an unresolved permission question, not evidence of a blanket prohibition on all
public-page reading. Robots permission to crawl is not a data-reuse license.

The [official seller agreement](https://edu.business.umico.az/space/knowledge/872513537)
describes authenticated merchant-account/API access. It does not establish access to
the whole consumer catalog for SuperChat. No publicly documented consumer search API,
authorized outbound product feed or applicable third-party reuse grant was verified.

## Feasible scope and outstanding limits

A bounded public-page reader could discover actual category links, read permitted
category/product HTML, normalize published product facts and locally filter/sort or
compare the returned subset. It should cache responses, limit page reads, respect
429/access denials, retain official links and report partial coverage. A missing local
match must not be presented as absence from Birmarket's entire catalog.

It must not call the disallowed keyword routes or imitate the storefront's private
backend calls. Platform-wide keyword search and native server-side filter URLs have
not been cleared by this investigation. Published stock labels must remain advertised
status, without quantity, reservation or delivery guarantees.

For a production integration, the remaining clarification with Birmarket/Competo is
whether SuperChat may automatically retrieve and redisplay titles, prices and images,
with what caching/attribution limits, and whether an approved search endpoint or feed
is available. No message was sent and no credentials were requested or created.

## Reproduce the evidence

`python scripts/inspect_birmarket_public.py` checks robots before public HTML requests,
reads the current terms and one product URL actually observed in the category markup,
and saves evidence under ignored `artifacts/provider-research/birmarket/`.
The application never reads these captures as a catalog or failure fallback.

`python scripts/inspect_birmarket_terms.py` opens only the public user-agreement dialog
in a temporary anonymous headless Edge session. It closes the initial city popup
without selecting a location and does not log in, search, add to cart or submit forms.

**Decision:** public HTML retrieval is technically verified; production data-reuse
permission and full search access remain unverified. No active Birmarket integration
has been enabled, and all working modules remain unchanged.
