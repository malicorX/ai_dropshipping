"""Parse amazon.de search result HTML (SERP) + structured filter helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, Iterable


@dataclass(frozen=True)
class SerpHit:
    asin: str
    title: str
    price_eur: float | None
    stars: float | None
    reviews: int | None
    sponsored: bool
    url: str


_ASIN_RE = re.compile(r"/dp/([A-Z0-9]{10})")
_PRICE_RE = re.compile(
    r"(?:€|EUR)\s*([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2})|([0-9]+),[0-9]{2}\s*€"
)
_STARS_RE = re.compile(
    r"([0-9]+(?:[.,][0-9]+)?)\s*(?:von\s*5|out of 5|Sterne|stars)",
    re.I,
)
_REVIEWS_RE = re.compile(
    r"([0-9]{1,3}(?:[.\s][0-9]{3})*|\d+)\s*(?:Bewertungen|ratings|reviews)",
    re.I,
)


def _parse_de_number(text: str) -> float | None:
    t = text.strip().replace("\xa0", " ").replace(".", "").replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def parse_price_text(text: str) -> float | None:
    if not text:
        return None
    m = _PRICE_RE.search(text)
    if m:
        raw = m.group(1) or m.group(2)
        if m.group(1):
            return _parse_de_number(m.group(1))
        return _parse_de_number(raw)
    m2 = re.search(r"(\d+)[.,](\d{2})", text)
    if not m2:
        return None
    return float(f"{m2.group(1)}.{m2.group(2)}")


def parse_stars_text(text: str) -> float | None:
    if not text:
        return None
    m = _STARS_RE.search(text)
    if not m:
        m = re.search(r"([0-9][.,][0-9])", text)
    if not m:
        return None
    return _parse_de_number(m.group(1))


def parse_reviews_text(text: str) -> int | None:
    if not text:
        return None
    m = _REVIEWS_RE.search(text)
    if m:
        digits = re.sub(r"[^\d]", "", m.group(1))
    else:
        digits = re.sub(r"[^\d]", "", text)
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def _parse_price(block: str) -> float | None:
    return parse_price_text(block)


def _parse_stars(block: str) -> float | None:
    return parse_stars_text(block)


def _parse_reviews(block: str) -> int | None:
    return parse_reviews_text(block)


class _ResultCardCollector(HTMLParser):
    """Rough split of HTML into result cards by data-asin attributes."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.cards: list[tuple[str, str]] = []
        self._current_asin: str | None = None
        self._depth = 0
        self._buf: list[str] = []
        self._capture = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        ad = {k: (v or "") for k, v in attrs}
        asin = ad.get("data-asin", "").strip()
        if tag in {"div", "span", "article"} and asin and len(asin) == 10:
            if self._capture and self._current_asin:
                self.cards.append((self._current_asin, "".join(self._buf)))
            self._current_asin = asin
            self._depth = 1
            self._buf = [f" data-asin={asin} "]
            self._capture = True
            if "AdHolder" in ad.get("class", "") or "sponsored" in ad.get("class", "").lower():
                self._buf.append(" SPONSORED ")
            return
        if self._capture:
            self._depth += 1
            if tag == "a" and ad.get("href"):
                self._buf.append(f" href={ad['href']} ")
            if tag == "span" and ad.get("aria-label"):
                self._buf.append(f" {ad['aria-label']} ")
            cls = ad.get("class", "")
            if "a-price" in cls or "a-icon-alt" in cls or "a-size-base" in cls:
                self._buf.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if self._capture:
            self._depth -= 1
            if self._depth <= 0 and self._current_asin:
                self.cards.append((self._current_asin, "".join(self._buf)))
                self._capture = False
                self._current_asin = None
                self._buf = []

    def handle_data(self, data: str) -> None:
        if self._capture and data.strip():
            self._buf.append(data)


def hits_from_dom_rows(rows: list[dict[str, Any]]) -> list[SerpHit]:
    """Build SerpHit list from Playwright page.evaluate() rows."""
    hits: list[SerpHit] = []
    seen: set[str] = set()
    for row in rows:
        asin = str(row.get("asin") or "").strip().upper()
        if len(asin) != 10 or asin in seen:
            continue
        seen.add(asin)
        price = row.get("price")
        stars = row.get("stars")
        reviews = row.get("reviews")
        if isinstance(price, str):
            price = parse_price_text(price)
        if isinstance(stars, str):
            stars = parse_stars_text(stars)
        if isinstance(reviews, str):
            reviews = parse_reviews_text(reviews)
        hits.append(
            SerpHit(
                asin=asin,
                title=str(row.get("title") or "")[:160],
                price_eur=float(price) if isinstance(price, (int, float)) else None,
                stars=float(stars) if isinstance(stars, (int, float)) else None,
                reviews=int(reviews) if isinstance(reviews, (int, float)) else None,
                sponsored=bool(row.get("sponsored")),
                url=str(row.get("url") or f"https://www.amazon.de/dp/{asin}").split("?")[0],
            )
        )
    return hits


def parse_serp_html(html: str) -> list[SerpHit]:
    collector = _ResultCardCollector()
    collector.feed(html)
    cards = collector.cards
    if not cards:
        cards = _fallback_cards(html)

    hits: list[SerpHit] = []
    seen: set[str] = set()
    for asin, block in cards:
        if asin in seen:
            continue
        seen.add(asin)
        sponsored = bool(
            re.search(r"Gesponsert|Sponsored|SPONSORED|AdHolder", block, re.I)
        )
        hits.append(
            SerpHit(
                asin=asin,
                title=_guess_title(block),
                price_eur=_parse_price(block),
                stars=_parse_stars(block),
                reviews=_parse_reviews(block),
                sponsored=sponsored,
                url=f"https://www.amazon.de/dp/{asin}",
            )
        )
    return hits


def _fallback_cards(html: str) -> list[tuple[str, str]]:
    cards: list[tuple[str, str]] = []
    for m in re.finditer(r'data-asin="([A-Z0-9]{10})"', html):
        asin = m.group(1)
        start = max(0, m.start() - 200)
        end = min(len(html), m.start() + 4000)
        cards.append((asin, html[start:end]))
    return cards


def _guess_title(block: str) -> str:
    candidates = re.findall(r"[A-Za-zÄÖÜäöüß0-9][^<\n]{20,120}", block)
    if not candidates:
        return ""
    for c in candidates:
        if "€" in c or "EUR" in c:
            continue
        if re.search(r"von 5|Bewertung|Sterne", c, re.I):
            continue
        return c.strip()[:160]
    return candidates[0].strip()[:160]


def summarize_hits(hits: Iterable[SerpHit]) -> dict[str, int]:
    items = list(hits)
    return {
        "total": len(items),
        "with_price": sum(1 for h in items if h.price_eur is not None),
        "with_stars": sum(1 for h in items if h.stars is not None),
        "with_reviews": sum(1 for h in items if h.reviews is not None),
        "sponsored": sum(1 for h in items if h.sponsored),
    }


def filter_hits(
    hits: Iterable[SerpHit],
    *,
    min_stars: float,
    min_reviews: int,
    price_min: float,
    price_max: float,
    skip_sponsored: bool,
) -> list[SerpHit]:
    out: list[SerpHit] = []
    for h in hits:
        if skip_sponsored and h.sponsored:
            continue
        if h.price_eur is None:
            continue
        if h.price_eur < price_min or h.price_eur > price_max:
            continue
        if h.stars is None or h.stars + 1e-9 < min_stars:
            continue
        if h.reviews is None or h.reviews < min_reviews:
            continue
        out.append(h)
    return out


# JS run inside Playwright page — Amazon.de SERP structure
DOM_EXTRACT_JS = """
() => {
  const out = [];
  const nodes = document.querySelectorAll('div[data-component-type="s-search-result"][data-asin], div[data-asin]');
  for (const el of nodes) {
    const asin = (el.getAttribute('data-asin') || '').trim();
    if (!asin || asin.length !== 10) continue;
    const titleEl = el.querySelector('h2 a span, h2 span, h2 a');
    const priceEl = el.querySelector('span.a-price span.a-offscreen, span.a-price .a-offscreen');
    const starsEl = el.querySelector('span.a-icon-alt, i.a-icon-star-small span.a-icon-alt, i.a-icon-star span.a-icon-alt');
    const reviewsEl = el.querySelector('span[aria-label*="Bewertung"], span[aria-label*="rating"], a[href*="#customerReviews"] span, span.a-size-base.s-underline-text');
    const sponsored = !!(
      el.querySelector('.puis-label-popover-default, .puis-sponsored-label-text, [data-component-type="sp-sponsored-result"]')
      || /Gesponsert|Sponsored/i.test(el.innerText.slice(0, 200))
      || (el.className || '').includes('AdHolder')
    );
    const href = el.querySelector('h2 a')?.getAttribute('href') || ('/dp/' + asin);
    out.push({
      asin,
      title: titleEl ? titleEl.textContent.trim() : '',
      price: priceEl ? priceEl.textContent.trim() : null,
      stars: starsEl ? starsEl.textContent.trim() : null,
      reviews: reviewsEl ? (reviewsEl.getAttribute('aria-label') || reviewsEl.textContent || '').trim() : null,
      sponsored,
      url: href.startsWith('http') ? href : ('https://www.amazon.de' + href),
    });
  }
  return out;
}
"""
