# SuperChat - five-minute Phase 1 demonstration

Use one conversation for the main sequence. It switches Flights → Shopping →
Cinema → Flights → Shopping: **four domain switches**, without selecting a mode.

## Before the timer

From the project directory, start a fresh process for known inventory:

```powershell
$env:SUPERCHAT_ROUTING_MODE = "offline"
.\.venv\Scripts\python.exe -m app.serve
```

Open http://127.0.0.1:8000/ and choose **New conversation**. The fixed competition
date is Monday, 2 November 2026. Use offline mode for this repeatable demonstration;
say so explicitly. If a live Gemini test succeeds beforehand, `auto` can be used
instead, but provider latency may change the timing. Never display `.env` or a key.

| Time | Action | What to explain / verify |
|---|---|---|
| 0:00-0:20 | Show the welcome page and sidebar. | One chat for three domains; official mock data; no payments or real bookings. Point out the local-assistant label if offline. |
| 0:20-0:50 | `Find flights from Baku to Istanbul on Friday, cheapest first.` | Friday resolves to November 6. F013 costs 175 AZN with one stop; F002 costs 245 AZN; F001 costs 289 AZN. All facts come from structured results. |
| 0:50-1:10 | `Only direct.` Then select both remaining cards and click **Compare selected**. | A short follow-up retains route/date; F002 and F001 remain. Compare baggage, duration, seats and prices. |
| 1:10-1:45 | `Show wireless headphones under 100 AZN.` Set quantity **2** on P001 and click **Add to cart**. | Switch 1: Shopping. Unit price 89.90 AZN; total 179.80 AZN. No purchase occurs. |
| 1:45-2:15 | `What movies are playing tonight?` | Switch 2: Cinema. Tonight is November 2. Show M001, M003 and M008 with their actual showtimes. S003 is sold out and its ticket action is disabled. |
| 2:15-2:40 | On showtime **S001**, choose **2** tickets and click **Mock tickets**. | Two tickets cost 24.00 AZN. Read the generated mock confirmation and the no-payment notice. IDs are created by successful Python operations, not Gemini. |
| 2:40-3:00 | `Back to flights.` | Switch 3: earlier route/date and selected flights return. No need to restate the search. |
| 3:00-3:25 | `Show my cart.` Click **Remove 1**. | Switch 4: headphones remain in this session. New total: 89.90 AZN. |
| 3:25-3:50 | `Find a flight from Baku to Istanbul on Friday and a backpack under 100 AZN.` | One message executes Flights and Shopping; both result sections are visible. P007 is the matching backpack, 69.90 AZN. |
| 3:50-4:10 | `Show me something good.` Then `What is the weather in Ganja?` | One short clarification for ambiguity; polite scope boundary for weather. No invented records. |
| 4:10-4:30 | Refresh, then click **New conversation** and send `Show my cart.` | Earlier chat stays in the sidebar. A new conversation has an empty cart; refresh preserves history. |
| 4:30-5:00 | Explain architecture and evidence. | Gemini structured intents → deterministic services → read-only repositories. Separate domain states, one shared history. 200 automated tests; real-browser desktop/mobile checks. Local category evaluation: 32/36 (88.9%) on a development corpus, not Gemini accuracy. Server state resets on restart. |

## If something goes wrong

- If Gemini is unavailable in auto mode, wait for the bounded call to fall back.
  Explain the local-assistant label and use the exact prompts above.
- If a connection drops after a mutation, use **Retry safely**. Do not create a new
  message to retry: the saved request ID prevents duplicate commits in the running process.
- If a session is archived after a backend restart, start a new conversation. Saved
  history is readable; it is not replayed into a new booking/cart session.
- If seats were consumed by earlier practice, restart your own backend before the
  timed demonstration. All inventory is mock and the official files stay unchanged.

Close by stating that the application is prepared for Render but has not been pushed
or deployed. Real APIs, payments, persistent storage and bonus tasks are not implemented.
