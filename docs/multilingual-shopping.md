# Shopping diagnostics and multilingual chat

The three reported laptop queries were checked against the documented public
BuyWhere search API. The API returned HTTP 200 with product records whose optional
`category_path` was null. One such row made the former list comprehension reject
the entire response as `invalid_response`. An unnormalized Azerbaijani request also
returned an explicitly degraded response; that remains a provider failure, never
a claim that no products exist.

The adapter now accepts missing categories, isolates invalid records, validates
prices/currencies locally, and ranks laptop records using their published title,
category and merchant URL. Laptop stands, brushes, bags and similar accessories
are excluded from device-only queries. All matching records from the bounded
provider response remain in session state; there is no seven-product API cutoff.
Unknown stock, shipping and price dates remain unknown.

`scripts/diagnose_buywhere.py` records anonymous request URLs and raw public
responses under ignored `artifacts/provider-research/buywhere/diagnostics/`.
`python scripts/diagnose_buywhere.py --verify` routes the three reported phrases,
asserts `query=laptops`, `currency=USD`, `max_price=500`, and verifies live filtered
results and cache reuse. No private routes or merchant pages are fetched.

Gemini continues to receive the original request and saved domain context.
Shared AZ/EN/RU normalization checks explicit dates, product subjects and monetary
constraints, including mixed-language clauses. The local outage grammar supports
the same tested intents in all three languages and asks for clarification outside
its supported grammar. This is not a claim of arbitrary-language benchmark parity.
Proper names, IDs, prices, links and source metadata are not model-generated.
Provider notices, errors and factual response templates are localized. Original
catalog titles and descriptions remain available as supplied by the source.

Language is detected each turn. Language-only commands update reply language
without searching again or clearing selections. `POST /api/chat` also accepts
optional `language: "az" | "en" | "ru"`. The page selector sets this preference;
otherwise the interface follows detected reply language. Generated Details/Compare
actions retain the last reply language. Request-ID replay isolation includes the
language preference. Cinema screening language is separate from reply language.

Discovery cards initially render seven records. Arrows, keyboard navigation or
swiping append further batches of seven from the existing response without losing
earlier cards or comparison selections. Mobile widths and reduced-motion settings
are supported. Details and comparisons keep the full information layout.

Run verification without opening a browser:

```shell
python -m pytest -q
node --test tests/ui_preferences.test.cjs tests/carousel.test.cjs
python scripts/diagnose_buywhere.py --verify
```
