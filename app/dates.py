"""Resolve relative expressions with a supplied date or the fixture reference."""

import re
from datetime import date, timedelta

from app.config import REFERENCE_DATE

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august",
          "september", "october", "november", "december")
MONTH_PATTERN = "|".join(month[:3] + "(?:" + month[3:] + ")?" for month in MONTHS)
DATE_PATTERN = (r"\b(?:\d{4}-\d{2}-\d{2}|day after tomorrow|in \d+ days?|"
                r"(?:next |this )?(?:" + "|".join(WEEKDAYS) + r")|tonight|tomorrow|today|"
                r"\d{1,2}(?:st|nd|rd|th)? (?:" + MONTH_PATTERN + r")(?:,? \d{4})?|"
                r"(?:" + MONTH_PATTERN + r") \d{1,2}(?:st|nd|rd|th)?(?:,? \d{4})?)\b")


def date_expression(message):
    """Return an explicit supported expression without inventing a date."""
    from app.languages import normalize_text
    semantic = re.sub(r'"[^"\n]+"|“[^”\n]+”', "", normalize_text(message))
    match = re.search(DATE_PATTERN, semantic, re.IGNORECASE)
    return match[0] if match else None


def resolve_date(expression: str, reference_date: date | None = None) -> date | None:
    base = reference_date or REFERENCE_DATE
    from app.languages import normalize_text
    text = normalize_text(expression)
    if text in {"today", "tonight"}:
        return base
    if text == "tomorrow":
        return base + timedelta(days=1)
    if text == "day after tomorrow":
        return base + timedelta(days=2)
    match = re.fullmatch(r"in (\d+) days?", text)
    if match:
        days = int(match[1])
        if days <= 3650:
            return base + timedelta(days=days)
        return None
    match = re.fullmatch(r"(?:(this|next|on) )?(" + "|".join(WEEKDAYS) + r")", text)
    if match:
        prefix, weekday = match.groups()
        offset = (WEEKDAYS.index(weekday) - base.weekday()) % 7
        if prefix == "next":
            # Explicit convention: next Friday means Friday of the following week.
            offset += 7
        return base + timedelta(days=offset)
    named = re.fullmatch(r"(\d{1,2})(?:st|nd|rd|th)? (" + MONTH_PATTERN + r")(?:,? (\d{4}))?", text)
    reverse = re.fullmatch(r"(" + MONTH_PATTERN + r") (\d{1,2})(?:st|nd|rd|th)?(?:,? (\d{4}))?", text)
    if named or reverse:
        day, month, year = named.groups() if named else (reverse[2], reverse[1], reverse[3])
        try:
            return date(int(year) if year else base.year,
                        next(i for i, name in enumerate(MONTHS, 1) if name.startswith(month)), int(day))
        except ValueError:
            return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None
