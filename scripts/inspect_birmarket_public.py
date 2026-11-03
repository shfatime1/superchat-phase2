"""Read-only Birmarket access research; never calls catalog/private JSON APIs.

Saves the public responses under ignored artifacts for review. No provider, routing,
application configuration or frontend is changed. Query-string robots rules matter.
"""

import json
from pathlib import Path
import re
import time
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
import httpx

ROOT = "https://birmarket.az"
AGENT = "SuperChat/2.0 (read-only public catalog research)"
OUTPUT = Path(__file__).resolve().parents[1] / "artifacts/provider-research/birmarket"


def robots_allowed(body, url):
    """Longest matching robots rule, including query strings and * / $ patterns."""
    groups, agents, rules = [], [], []
    for raw in body.splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, value = (part.strip() for part in line.split(":", 1))
        if key.casefold() == "user-agent":
            if rules:
                groups.append((agents, rules))
                agents, rules = [], []
            agents.append(value.casefold())
        elif key.casefold() in {"allow", "disallow"} and agents and value:
            rules.append((key.casefold(), value))
    if agents:
        groups.append((agents, rules))
    eligible = [(len(a) if a != "*" else 0, entries) for names, entries in groups for a in names
                if a == "*" or a in AGENT.casefold()]
    if not eligible:
        return True
    priority = max(rank for rank, _ in eligible)
    parsed = urlsplit(url)
    target = parsed.path + ("?" + parsed.query if parsed.query else "")
    matches = []
    for rank, entries in eligible:
        if rank != priority:
            continue
        for kind, pattern in entries:
            core = pattern[:-1] if pattern.endswith("$") else pattern
            expression = "^" + re.escape(core).replace(r"\*", ".*") + ("$" if pattern.endswith("$") else "")
            if re.search(expression, target):
                matches.append((len(core.replace("*", "")), kind == "allow"))
    return max(matches)[1] if matches else True


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=20, follow_redirects=False, headers={"User-Agent": AGENT}) as client:
        robots = client.get(ROOT + "/robots.txt")
        print("robots", robots.status_code, flush=True)
        robots.raise_for_status()
        policy = robots.text
        (OUTPUT / "robots.txt").write_text(policy, encoding="utf-8")
        print(policy, flush=True)
        # Legal URL is published in the official seller agreement. Category URL
        # was observed in the public homepage navigation, not guessed from an API.
        pages = [("legal", "/legal/market_termsofuse"), ("home", "/"),
                 ("current-terms", "/shopping-public-offer"),
                 ("category", "/categories/2-telefonlar-ve-aksessuarlar"),
                 ("sitemap", "/sitemap.xml")]
        for label, path in pages:
            url = ROOT + path
            if not robots_allowed(policy, url):
                print(label, "SKIPPED robots disallow", flush=True)
                continue
            time.sleep(1)
            r = client.get(url)
            print(label, r.status_code, r.headers.get("content-type"), "location", r.headers.get("location"), flush=True)
            if r.status_code != 200:
                continue  # No retries, alternate identities, challenge solving or bypass.
            (OUTPUT / (label + ".txt" if label == "sitemap" else label + ".html")).write_text(r.text, encoding="utf-8")
            if label == "sitemap":
                print(r.text[:3000].encode("ascii", "backslashreplace").decode(), flush=True)
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            links = [{"text": a.get_text(" ", strip=True), "href": a.get("href")} for a in soup.select("a[href]")
                     if any(term in (a.get("href", "") + " " + a.get_text()).casefold()
                            for term in ("legal", "terms", "razılaş", "istifad", "privacy", "product", "feed", "sitemap"))]
            structured = soup.select('script[type="application/ld+json"]')
            print(json.dumps({"title": soup.title.get_text() if soup.title else None,
                "bytes": len(r.content), "product_links": sum("/product/" in a.get("href", "") for a in soup.select("a[href]")),
                "json_ld_count": len(structured), "matching_links": links[:30]}, ensure_ascii=True), flush=True)
            if label in {"legal", "current-terms"}:
                for tag in soup(["script", "style", "nav", "header", "footer"]):
                    tag.decompose()
                visible = soup.get_text(" ", strip=True)
                (OUTPUT / (label + ".txt")).write_text(visible, encoding="utf-8")
                print("Legal text saved for review:", label, len(visible), "characters", flush=True)
            for block in structured:
                try:
                    data = json.loads(block.get_text())
                    print("JSON-LD type", data.get("@type") if isinstance(data, dict) else "array", flush=True)
                    if label == "category" and isinstance(data, dict):
                        items = data.get("mainEntity", {}).get("itemListElement", [])
                        facts = []
                        for entry in items:
                            item = entry.get("item", {})
                            offer = item.get("offers", {})
                            facts.append({"id": item.get("sku"), "title": item.get("name"),
                                "product_url": item.get("url"), "image_url": item.get("image"),
                                "brand": item.get("brand", {}).get("name"),
                                "price": offer.get("price"), "currency": offer.get("priceCurrency"),
                                "advertised_availability": offer.get("availability")})
                        # Evidence only; the application never reads this capture.
                        (OUTPUT / "observed-products.json").write_text(json.dumps(facts, ensure_ascii=False, indent=2), encoding="utf-8")
                        print("Published product records", len(facts), flush=True)
                        if facts:
                            product = facts[0].get("product_url", "")
                            if urlsplit(product).netloc == "birmarket.az" and urlsplit(product).path.startswith("/product/") and robots_allowed(policy, product):
                                time.sleep(1)
                                detail = client.get(product)
                                print("Observed product page", detail.status_code, product, flush=True)
                                if detail.status_code == 200:
                                    (OUTPUT / "product.html").write_text(detail.text, encoding="utf-8")
                                    detail_soup = BeautifulSoup(detail.text, "html.parser")
                                    print("Product JSON-LD blocks", len(detail_soup.select('script[type="application/ld+json"]')), flush=True)
                except ValueError:
                    print("Invalid JSON-LD", flush=True)


if __name__ == "__main__":
    main()
