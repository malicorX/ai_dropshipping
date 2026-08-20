"""Amazon.de search URL construction."""

from __future__ import annotations

from urllib.parse import quote_plus, urlencode


def build_search_url(
    keyword: str,
    *,
    price_min_eur: float,
    price_max_eur: float,
    page: int = 1,
) -> str:
    """Build amazon.de search URL with price band (p_36 uses Euro-cents)."""
    lo = max(0, int(round(price_min_eur * 100)))
    hi = max(lo, int(round(price_max_eur * 100)))
    params = {
        "k": keyword,
        "rh": f"p_36:{lo}-{hi}",
        "page": str(max(1, page)),
    }
    return f"https://www.amazon.de/s?{urlencode(params, quote_via=quote_plus)}"
