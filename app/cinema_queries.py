"""Normalize chain-wide discovery without discarding real cinema constraints."""

import re

from app.schemas import CinemaParameters


CHAIN = r"(?:cinema\s*plus|cine\s*mastercard)(?:\s+azerbaijan)?"


def normalized_cinema_parameters(parameters):
    """A provider/chain name is not an individual branch or a movie title."""
    p = parameters.model_copy(deep=True)
    if p.cinema_name and re.fullmatch(CHAIN, p.cinema_name.strip(), re.I):
        p.cinema_name = None
    if p.movie_title and re.fullmatch(
        rf"(?:{CHAIN}|all(?:\s+{CHAIN})?(?:\s+(?:movies|films))?)", p.movie_title.strip(), re.I
    ):
        p.movie_title = None
    return p


def normalize_cinema_discovery(message, result):
    """An explicit unqualified 'all movies' request starts a fresh cinema list.

    Match the entire request so named films, branches, dates, budgets and screening
    languages continue through normal extraction and state merging.
    """
    if len(result.intents) != 1 or result.intents[0].domain != "cinema":
        return result
    intent = result.intents[0]
    if intent.intent not in {"search", "details", "filter", "follow_up"}:
        return result
    text = message.casefold().strip(" .?!")
    text = re.sub(r"^(?:please\s+)?(?:show(?:\s+me)?|list|find(?:\s+me)?)\s+", "", text)
    if re.fullmatch(rf"all\s+(?:{CHAIN}\s+)?(?:movies|films)", text):
        intent.parameters = CinemaParameters()
        intent.intent = "search"
        intent.reset_context = True
    return result
