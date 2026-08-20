"""ASIN / Amazon URL helpers and hard-reject checks."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from dropship_desk.models import MarginSettings, OfferIn

_ASIN_RE = re.compile(r"\b([A-Z0-9]{10})\b")
_DACH = frozenset({"DE", "AT", "CH", "DEUTSCHLAND", "ÖSTERREICH", "OESTERREICH", "SCHWEIZ"})


def extract_asin(asin_or_url: str) -> str:
    text = (asin_or_url or "").strip()
    if not text:
        return ""
    if re.fullmatch(r"[A-Z0-9]{10}", text, re.I):
        return text.upper()
    # /dp/ASIN or /gp/product/ASIN
    m = re.search(r"/(?:dp|gp/product|product)/([A-Z0-9]{10})", text, re.I)
    if m:
        return m.group(1).upper()
    parsed = urlparse(text)
    m2 = _ASIN_RE.search(parsed.path.upper())
    if m2:
        return m2.group(1)
    m3 = _ASIN_RE.search(text.upper())
    return m3.group(1) if m3 else ""


def hard_reject_reasons(offer: OfferIn, settings: MarginSettings) -> list[str]:
    reasons: list[str] = []
    if offer.amazon_total <= 0:
        reasons.append("no reliable amazon_total")
    if not offer.in_stock:
        reasons.append("out of stock")
    if offer.delivery_days is not None and offer.delivery_days > settings.max_delivery_days:
        reasons.append(
            f"delivery_days {offer.delivery_days} > max {settings.max_delivery_days}"
        )
    if settings.skip_sold_by_amazon and offer.sold_by_amazon:
        reasons.append("sold by Amazon (skipped)")
    if settings.reject_dach_sellers and offer.seller_country:
        country = offer.seller_country.strip().upper()
        if country in _DACH:
            reasons.append(f"DACH seller ({offer.seller_country})")
    return reasons
