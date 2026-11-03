"""Resolve relative expressions with a supplied date or the fixture reference."""

import re
from datetime import date, timedelta

from app.config import REFERENCE_DATE

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def resolve_date(expression: str, reference_date: date | None = None) -> date | None:
    base = reference_date or REFERENCE_DATE
    text = expression.strip().lower()
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
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None
