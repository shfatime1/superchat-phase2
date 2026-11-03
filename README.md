# SuperChat — Phase 2

**SuperChat** is an AI-powered conversational assistant that combines **Flights, Shopping, and Cinema** in a single chat interface.

Powered by **Google Gemini**, it automatically identifies user intent, switches between domains, and preserves conversation context.

The application supports **Azerbaijani, English, and Russian**.

## Key Features

- **Intelligent Routing:** Automatic domain switching, mixed intents, follow-up questions, and context preservation.
- **Flights:** Search, filter, sort, and compare flight offers using the Travelpayouts API.
- **Shopping:** Search, filter, and compare products through BuyWhere.
- **Cinema:** Discover movies, cinemas, and published showtimes from CinemaPlus.
- **Multilingual Support:** AZ/EN/RU conversations, including language switching.
- **Voice Input:** Speech-to-text with automatic voice activity detection (VAD).
- **Visual Search:** Upload an image and find matching products using Gemini Vision and BuyWhere.
- **Streaming:** Live response updates and processing progress.
- **Caching:** 30-minute session-isolated caching.
- **Debugger:** Routing decisions, provider calls, response times, and sanitized errors.

## Technology Stack

| Component | Technology |
|---|---|
| Backend | Python, FastAPI |
| Frontend | HTML, CSS, JavaScript |
| AI | Google Gemini |
| Flights | Travelpayouts API |
| Shopping | BuyWhere API |
| Cinema | CinemaPlus public listings |
| Voice | MediaRecorder, Web Audio API, Gemini |
| Deployment | Render |

## Architecture

```text
User → Chat Interface → FastAPI
                          |
                    Gemini Router
                    (Local Fallback)
                          |
           +--------------+--------------+
           |              |              |
         Flights       Shopping        Cinema
           |              |              |
      Travelpayouts     BuyWhere      CinemaPlus
           |              |              |
           +--------------+--------------+
                          |
                  Chat Response
```

Separate domain states preserve previous searches and support context-aware follow-ups.

## Installation

**Requirements:** Python 3.12, Gemini API key, Travelpayouts API token.

### 1. Install dependencies

```bash
python -m pip install -r requirements.txt
```

### 2. Configure environment variables

```env
GEMINI_API_KEY=your_key
TRAVELPAYOUTS_API_TOKEN=your_token
SUPERCHAT_ROUTING_MODE=auto
SUPERCHAT_DATA_MODE=providers
SHOPPING_PROVIDER=buywhere
CINEMA_PROVIDER=auto
PROVIDER_CACHE_TTL=1800
```

### 3. Run the application

```bash
python -m app.serve
```

Open **http://localhost:8000**.

## Deployment

Deployed using **Render**.

- **Build:** `pip install -r requirements.txt`
- **Start:** `python -m app.serve`
- **Health check:** `/health`

Set API credentials securely using Render Environment Variables and enable `COOKIE_SECURE=true`.

## Testing

Run the automated tests:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

The eight reference conversation scenarios passed focused local fixture-mode checks, covering routing, follow-ups, mixed intents, ambiguity, and out-of-scope handling.

Additional focused checks cover multilingual routing, filtering, provider failures, Voice Input, and Visual Search.

## Limitations

- Flight fares may be cached; live seat availability and bookings are not supported.
- Shopping prices may be outdated; live stock and checkout are not verified.
- CinemaPlus provides public listings, not private seat inventory or reservations.
- External API connectivity and rate limits may affect responses.

SuperChat does not invent unavailable provider information.

---

**SuperChat Phase 2** — A unified, multilingual AI assistant for flights, shopping, and cinema.