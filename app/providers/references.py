"""Resolve references only against displayed provider records, never guessed IDs."""
from decimal import Decimal
from app.domains.common import DomainIssue
from app.languages import normalize_text


def saved_ids(ctx, explicit=None, positions=None, reference=None, compare=False):
    if explicit:
        return list(dict.fromkeys(explicit))
    if positions:
        if any(i < 1 or i > len(ctx.last_result_ids) for i in positions):
            raise DomainIssue("invalid_selection")
        return list(dict.fromkeys(ctx.last_result_ids[i - 1] for i in positions))
    rows = [r for r in ctx.provider_snapshot.get("items", []) if r["id"] in ctx.last_result_ids]
    if reference:
        text = normalize_text(reference).strip(" .?!")
        if text in {"all", "both", "them", "all of them", "both of them"}:
            return ctx.last_result_ids.copy()
        if text in {"it", "that", "this", "the one", "that one", "this one"}:
            return ctx.selected_ids.copy() or (ctx.last_result_ids.copy() if len(ctx.last_result_ids) == 1 else [])
        if "cheap" in text or "expensive" in text:
            priced = [r for r in rows if r.get("price")]
            if not priced or len({r["price"]["currency"] for r in priced}) != 1:
                raise DomainIssue("choose_item")
            value = (max if "expensive" in text else min)(Decimal(r["price"]["amount"]) for r in priced)
            ids = [r["id"] for r in priced if Decimal(r["price"]["amount"]) == value]
        else:
            genres = ("sci-fi", "comedy", "drama", "thriller", "action", "horror", "animation", "adventure")
            ids = [r["id"] for r in rows if
                   any(any(genre in text and genre in normalize_text(g).replace("science fiction", "sci-fi") for genre in genres)
                       for g in r.get("genre", []) if g)
                   or any(str(r.get(k) or "").casefold() in text for k in ("title", "flight_number") if r.get(k))]
        if not ids or len(ids) > 1 and not compare:
            raise DomainIssue("choose_item")
        return ids
    return ctx.last_result_ids.copy() if compare else ctx.selected_ids.copy()
