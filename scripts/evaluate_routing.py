"""Reproducible local category evaluation. No external calls or secrets."""
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.chat import ChatService
from app.config import Settings
from app.domains.engine import DomainEngine
from app.fallback import LocalRouter
from app.repositories import Repositories
from app.responses import GeminiResponseFormulator
from app.state import SessionStore

# Each case starts in an independent session. Prefixes are real earlier turns.
CASES = [
    ([], "Find me a flight from Baku to Istanbul on Friday.", "flights"),
    ([], "Flights to Istanbul", "flights"),
    ([], "Compare flights F001 and F002", "flights"),
    ([], "Show details for flight F013", "flights"),
    ([], "Reserve flight F002 for 1 passenger", "flights"),
    ([], "Do you have wireless headphones under 100 AZN?", "shopping"),
    ([], "Show me laptops cheapest first", "shopping"),
    ([], "Add 2 P001 to my cart", "shopping"),
    ([], "Show my cart", "shopping"),
    ([], "Compare products P003 and P004", "shopping"),
    ([], "What is playing tonight?", "cinema"),
    ([], "Show sci-fi movies on Saturday", "cinema"),
    ([], "Movies rated above 8", "cinema"),
    ([], "Show details and showtimes for movie M001", "cinema"),
    ([], "Reserve 2 tickets for showtime S001", "cinema"),
    ([], "Find flights from Baku to Istanbul on Friday and a backpack under 100 AZN", "mixed"),
    ([], "Show laptops and movies tonight", "mixed"),
    ([], "Flights from Baku to Istanbul Friday; headphones under 100; movies tonight", "mixed"),
    (["Show me laptops"], "The second one, is it in stock?", "follow_up"),
    (["Flights from Baku to Istanbul Friday"], "And Saturday?", "follow_up"),
    (["Flights from Baku to Istanbul Friday"], "The cheaper one", "follow_up"),
    (["Show headphones", "What is playing tonight?"], "Back to the headphones", "follow_up"),
    (["What is playing tonight?", "Show laptops"], "The sci-fi one, any seats on Saturday?", "follow_up"),
    (["Reserve flight F002"], "Two passengers", "follow_up"),
    ([], "Show me something good", "ambiguous"),
    ([], "Book it", "ambiguous"),
    ([], "Book two seats", "ambiguous"),
    (["Show laptops and movies tonight"], "The first one", "ambiguous"),
    ([], "What is the weather in Ganja?", "out_of_scope"),
    ([], "Write a poem", "out_of_scope"),
    ([], "Help me write code", "out_of_scope"),
    ([], "Who is the president?", "out_of_scope"),
    # Intentional vocabulary challenges beyond the limited outage grammar.
    ([], "I need footwear for jogging", "shopping"),
    ([], "Are there any screenings in Nizami?", "cinema"),
    ([], "Which carrier goes to Dubai?", "flights"),
    ([], "Tell me a joke", "out_of_scope"),
]


def main():
    records = Repositories.from_json(ROOT / "data")
    rows, counts = [], Counter()
    for prefix, message, expected in CASES:
        service = ChatService(LocalRouter(records), SessionStore(), GeminiResponseFormulator(Settings()))
        service.engine = DomainEngine(records)
        sid = None
        for context in prefix:
            sid = service.chat(context, sid).session_id
        actual = service.chat(message, sid).routing.category.value
        rows.append((prefix, message, expected, actual))
        counts[expected, actual] += 1
    correct = sum(e == a for _, _, e, a in rows)
    categories = ["flights", "shopping", "cinema", "mixed", "follow_up", "ambiguous", "out_of_scope"]
    lines = ["# Phase 1 routing test log", "", f"Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}. Competition reference: **2026-11-02**.", "",
        "## Local outage router: executed evaluation", "",
        f"**{correct}/{len(rows)} correct ({100 * correct / len(rows):.1f}%)** category accuracy on a hand-written English development corpus. "
        "Each case has an independent session; context turns use the real domain engine. No Gemini calls. "
        "This is not a held-out benchmark, live-model score, or guarantee of semantic extraction accuracy.", "",
        "Run: `.\\.venv\\Scripts\\python.exe scripts/evaluate_routing.py`.", "",
        "| Expected category | Correct / total | Accuracy |", "|---|---:|---:|"]
    for category in categories:
        total = sum(v for (expected, _), v in counts.items() if expected == category)
        matched = counts[category, category]
        lines.append(f"| {category} | {matched} / {total} | {matched / total * 100:.1f}% |")
    lines += ["", "## Individual cases", "", "| # | Prior turns | Current message | Expected | Actual |", "|---:|---|---|---|---|"]
    for index, (prefix, message, expected, actual) in enumerate(rows, 1):
        lines.append(f"| {index} | {' → '.join(prefix) or '(new session)'} | {message} | {expected} | {actual} |")
    lines += ["", "## Error analysis", "",
        "The vocabulary challenges expose limited coverage: footwear, screenings, carriers and jokes receive "
        "clarification rather than a guessed domain or operation. Gemini is intended to understand broader phrasing when available. "
        "Category accuracy alone does not measure dates, record selection, quantities or operation success; these have separate integration tests.", "",
        "## Live Gemini smoke test: unavailable, not an accuracy result", "",
        "The earlier live smoke test used `gemini-flash-latest` with a configured key (never printed). "
        "Flights, Shopping, Cinema and Mixed requests all reported HTTP 504 with the original 30-second timeout. "
        "A longer 60-second retry also failed; a minimal generation request returned HTTP 503. "
        "**Successful live classifications: 0/4; semantic accuracy: not measurable**, because no classifications were returned. "
        "No further paid calls were used for this evaluation. Recheck model availability before a live Gemini demo.", "",
        "## Application verification", "",
        "See `verification.md` for executed pytest, browser and syntax checks. Mocked classifications validate "
        "application contracts, not Gemini accuracy. Outage tests cover provider/invalid responses, circuit recovery, "
        "no-key mode, uncertain mutations, reference dates, domain returns and grounded operations.", ""]
    path = ROOT / "docs" / "routing_test_log.md"
    path.parent.mkdir(exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Local category evaluation: {correct}/{len(rows)} ({100 * correct / len(rows):.1f}%). {path}")


if __name__ == "__main__":
    main()
