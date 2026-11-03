import re
from decimal import Decimal

from app.domain_models import DomainResult, PendingOperation
from app.domains.common import DomainIssue, by_ids, money, price_range, resolve_ids, result, same, total


class ShoppingService:
    def __init__(self, repository):
        self.repo = repository

    def search(self, p):
        price_range(p)
        tokens = re.findall(r"\w+", (p.query or "").casefold())
        # Simple plural matching; Gemini normalizes more complex search terms.
        tokens = [token[:-1] if token.endswith("s") and len(token) > 3 else token for token in tokens]
        tokens = ["smartphone" if token == "phone" else token for token in tokens]
        rows = []
        for row in self.repo.list_all():
            # Product identity must match; incidental description mentions are not alternatives.
            text = " ".join([*row.name.model_dump().values(), row.category, row.brand]).casefold()
            words = re.findall(r"\w+", text)
            words = {word[:-1] if word.endswith("s") and len(word) > 3 else word for word in words}
            if not all(token in words for token in tokens):
                continue
            if any(value and not same(value, getattr(row, key)) for key, value in
                   (("category", p.category), ("brand", p.brand), ("color", p.color))):
                continue
            if p.min_price_azn is not None and row.price_azn < p.min_price_azn:
                continue
            if p.max_price_azn is not None and row.price_azn > p.max_price_azn:
                continue
            if p.in_stock is not None and (row.stock > 0) != p.in_stock:
                continue
            rows.append(row)
        # Prefer actual named products over incidental mentions in descriptions
        # (a backpack with a laptop compartment is not itself a laptop).
        if tokens:
            named = [row for row in rows if all(token in " ".join(
                [*row.name.model_dump().values(), row.category, row.brand]).casefold() for token in tokens)]
            if named:
                rows = named
        sorts = {"price_asc": ("price_azn", False), "price_desc": ("price_azn", True),
                 "rating_desc": ("rating", True), "rating_asc": ("rating", False)}
        if p.sort_by:
            if p.sort_by not in sorts:
                raise DomainIssue("invalid_sort", status="error")
            field, reverse = sorts[p.sort_by]
            rows.sort(key=lambda row: getattr(row, field), reverse=reverse)
        return rows

    def cart(self, ctx):
        lines, amount = [], Decimal("0")
        for product_id, quantity in ctx.cart.items():
            product = by_ids(self.repo, [product_id])[0]
            subtotal = total(product.price_azn, quantity)
            amount += Decimal(subtotal)
            lines.append({"product": product.model_dump(mode="json"), "quantity": quantity,
                          "unit_price_azn": money(product.price_azn), "subtotal_azn": subtotal})
        return {"lines": lines, "total_azn": money(amount), "currency": "AZN"}

    def execute(self, extracted, session):
        ctx, delta = session.shopping, extracted.parameters
        action = extracted.intent
        if action == "follow_up":
            action = ctx.pending.action if ctx.pending else "details" if delta.reference or delta.result_positions else "search"
        if action == "resume" and ctx.selected_ids:
            action = "details"
        if action in {"search", "filter", "sort", "resume"}:
            ctx.pending = None
            rows = self.search(ctx.parameters)
            ctx.last_result_ids, ctx.selected_ids = [row.id for row in rows], []
            return result("shopping", action, "products", rows)
        if action == "cart_view":
            ctx.pending = None
            ctx.last_result_ids = list(ctx.cart)
            return DomainResult(domain="shopping", operation=action, code="cart", data={"cart": self.cart(ctx)})
        if action not in {"details", "compare", "availability", "cart_add", "cart_remove"}:
            raise DomainIssue("unsupported_operation", status="error")
        pending = ctx.pending if ctx.pending and ctx.pending.action == action else None
        explicit = delta.product_ids
        candidates = []
        if explicit is None and (delta.query or delta.category or delta.brand or delta.color):
            candidates = self.search(ctx.parameters)
            if action == "cart_remove":
                candidates = [row for row in candidates if row.id in ctx.cart]
            explicit = [row.id for row in candidates]
            ctx.last_result_ids = explicit.copy()
            if not explicit:
                return result("shopping", action, "products", [])
        ids = resolve_ids(self.repo, explicit, delta.result_positions,
                          None if extracted.intent == "resume" else delta.reference,
                          ctx.last_result_ids, pending.ids if pending and pending.ids else ctx.selected_ids)
        if action == "compare" and not ids and not delta.reference:
            ids = ctx.last_result_ids.copy()
        quantity = delta.quantity or (pending.quantity if pending else None)
        if action in {"cart_add", "cart_remove"} and (len(ids) != 1 or quantity is None):
            ctx.pending = PendingOperation(action=action, ids=ids, quantity=quantity)
            raise DomainIssue("cart_item", missing=(["product_id"] if len(ids) != 1 else []) +
                              (["quantity"] if quantity is None else []),
                              data={"products": [row.model_dump(mode="json") for row in candidates]})
        if not ids or action == "compare" and len(ids) < 2:
            raise DomainIssue("compare_items" if action == "compare" else "choose_item")
        rows = by_ids(self.repo, ids)
        if action in {"cart_add", "cart_remove"}:
            row = rows[0]
            if delta.max_price_azn is not None and row.price_azn > delta.max_price_azn \
                    or delta.min_price_azn is not None and row.price_azn < delta.min_price_azn \
                    or delta.color and not same(row.color, delta.color) \
                    or delta.brand and not same(row.brand, delta.brand):
                raise DomainIssue("selection_mismatch")
            current = ctx.cart.get(row.id, 0)
            if action == "cart_add":
                if current + quantity > row.stock:
                    raise DomainIssue("insufficient_stock", status="error", data={"available": row.stock, "in_cart": current})
                ctx.cart[row.id] = current + quantity
            else:
                if quantity > current:
                    raise DomainIssue("cart_quantity", status="error", data={"in_cart": current})
                if quantity == current:
                    ctx.cart.pop(row.id)
                else:
                    ctx.cart[row.id] = current - quantity
            ctx.selected_ids, ctx.pending = ids, None
            ctx.last_result_ids = list(ctx.cart)
            return DomainResult(domain="shopping", operation=action, code="cart", data={"cart": self.cart(ctx)})
        ctx.selected_ids, ctx.pending = ids, None
        ctx.last_result_ids = ids.copy()
        return result("shopping", action, "products", rows)
