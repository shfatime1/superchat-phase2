# Phase 1 routing test log

Generated: 2026-11-02T13:44:06+00:00. Competition reference: **2026-11-02**.

## Local outage router: executed evaluation

**32/36 correct (88.9%)** category accuracy on a hand-written English development corpus. Each case has an independent session; context turns use the real domain engine. No Gemini calls. This is not a held-out benchmark, live-model score, or guarantee of semantic extraction accuracy.

Run: `.\.venv\Scripts\python.exe scripts/evaluate_routing.py`.

| Expected category | Correct / total | Accuracy |
|---|---:|---:|
| flights | 5 / 6 | 83.3% |
| shopping | 5 / 6 | 83.3% |
| cinema | 5 / 6 | 83.3% |
| mixed | 3 / 3 | 100.0% |
| follow_up | 6 / 6 | 100.0% |
| ambiguous | 4 / 4 | 100.0% |
| out_of_scope | 4 / 5 | 80.0% |

## Individual cases

| # | Prior turns | Current message | Expected | Actual |
|---:|---|---|---|---|
| 1 | (new session) | Find me a flight from Baku to Istanbul on Friday. | flights | flights |
| 2 | (new session) | Flights to Istanbul | flights | flights |
| 3 | (new session) | Compare flights F001 and F002 | flights | flights |
| 4 | (new session) | Show details for flight F013 | flights | flights |
| 5 | (new session) | Reserve flight F002 for 1 passenger | flights | flights |
| 6 | (new session) | Do you have wireless headphones under 100 AZN? | shopping | shopping |
| 7 | (new session) | Show me laptops cheapest first | shopping | shopping |
| 8 | (new session) | Add 2 P001 to my cart | shopping | shopping |
| 9 | (new session) | Show my cart | shopping | shopping |
| 10 | (new session) | Compare products P003 and P004 | shopping | shopping |
| 11 | (new session) | What is playing tonight? | cinema | cinema |
| 12 | (new session) | Show sci-fi movies on Saturday | cinema | cinema |
| 13 | (new session) | Movies rated above 8 | cinema | cinema |
| 14 | (new session) | Show details and showtimes for movie M001 | cinema | cinema |
| 15 | (new session) | Reserve 2 tickets for showtime S001 | cinema | cinema |
| 16 | (new session) | Find flights from Baku to Istanbul on Friday and a backpack under 100 AZN | mixed | mixed |
| 17 | (new session) | Show laptops and movies tonight | mixed | mixed |
| 18 | (new session) | Flights from Baku to Istanbul Friday; headphones under 100; movies tonight | mixed | mixed |
| 19 | Show me laptops | The second one, is it in stock? | follow_up | follow_up |
| 20 | Flights from Baku to Istanbul Friday | And Saturday? | follow_up | follow_up |
| 21 | Flights from Baku to Istanbul Friday | The cheaper one | follow_up | follow_up |
| 22 | Show headphones → What is playing tonight? | Back to the headphones | follow_up | follow_up |
| 23 | What is playing tonight? → Show laptops | The sci-fi one, any seats on Saturday? | follow_up | follow_up |
| 24 | Reserve flight F002 | Two passengers | follow_up | follow_up |
| 25 | (new session) | Show me something good | ambiguous | ambiguous |
| 26 | (new session) | Book it | ambiguous | ambiguous |
| 27 | (new session) | Book two seats | ambiguous | ambiguous |
| 28 | Show laptops and movies tonight | The first one | ambiguous | ambiguous |
| 29 | (new session) | What is the weather in Ganja? | out_of_scope | out_of_scope |
| 30 | (new session) | Write a poem | out_of_scope | out_of_scope |
| 31 | (new session) | Help me write code | out_of_scope | out_of_scope |
| 32 | (new session) | Who is the president? | out_of_scope | out_of_scope |
| 33 | (new session) | I need footwear for jogging | shopping | ambiguous |
| 34 | (new session) | Are there any screenings in Nizami? | cinema | ambiguous |
| 35 | (new session) | Which carrier goes to Dubai? | flights | ambiguous |
| 36 | (new session) | Tell me a joke | out_of_scope | ambiguous |

## Error analysis

The vocabulary challenges expose limited coverage: footwear, screenings, carriers and jokes receive clarification rather than a guessed domain or operation. Gemini is intended to understand broader phrasing when available. Category accuracy alone does not measure dates, record selection, quantities or operation success; these have separate integration tests.

## Live Gemini smoke test: unavailable, not an accuracy result

The earlier live smoke test used `gemini-flash-latest` with a configured key (never printed). Flights, Shopping, Cinema and Mixed requests all reported HTTP 504 with the original 30-second timeout. A longer 60-second retry also failed; a minimal generation request returned HTTP 503. **Successful live classifications: 0/4; semantic accuracy: not measurable**, because no classifications were returned. No further paid calls were used for this evaluation. Recheck model availability before a live Gemini demo.

## Application verification

See `verification.md` for executed pytest, browser and syntax checks. Mocked classifications validate application contracts, not Gemini accuracy. Outage tests cover provider/invalid responses, circuit recovery, no-key mode, uncertain mutations, reference dates, domain returns and grounded operations.
