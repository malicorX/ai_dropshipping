"""Fetch a single amazon.de product detail page (PDP) for accurate price."""

from __future__ import annotations

import random
import re
import time
from typing import Any

from dropship_desk.amazon.serp import parse_price_text, parse_reviews_text, parse_stars_text
from dropship_desk.amazon.variations import (
    VariationChild,
    apply_variation_label,
    parse_variation_children,
)
from dropship_desk.models import OfferIn

MAX_VARIATION_CHILDREN = 8
_CHILD_PAUSE_SEC = 1.2

# Reliable-fetch policy (S2-T2a).  The gap applies between consecutive ASIN
# loads in this process; the cap applies to consecutive terminal ASIN
# failures (not individual retry attempts).
MIN_GAP_SEC = 5.0
MAX_CONSECUTIVE_FAILURES = 20
MAX_FETCH_ATTEMPTS = 3
_BACKOFF_BASE_SEC = 5.0
_BACKOFF_JITTER_SEC = 1.0
_BLOCK_PAGE_MAX_CHARS = 20_000
_PRODUCT_TITLE_RE = re.compile(r"""id\s*=\s*["']productTitle["']""", re.IGNORECASE)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_NOT_FOUND_TITLE_MARKERS = ("seite wurde nicht gefunden", "page not found")

_last_load_monotonic: float | None = None
_consecutive_failures = 0


class AmazonUnreachable(RuntimeError):
    """Every allowed attempt to load one ASIN failed in a retryable way."""


class AsinNotFound(RuntimeError):
    """Amazon reports the ASIN does not exist or was delisted (terminal)."""


class ChromeNotFound(RuntimeError):
    """The installed Chrome channel/executable cannot be launched."""


class _BlockedPageError(RuntimeError):
    """Amazon served a short interstitial instead of a product detail page."""


def reset_fetch_state() -> None:
    """Reset pacing and consecutive-failure state (used by tests)."""
    global _last_load_monotonic, _consecutive_failures
    _last_load_monotonic = None
    _consecutive_failures = 0


def _playwright():
    """Import Playwright lazily so importing this module needs no browser."""
    from playwright.sync_api import sync_playwright

    return sync_playwright()


def _launch_browser(p):
    """Launch the installed Chrome (not bundled Chromium), headless."""
    return p.chromium.launch(channel="chrome", headless=True)


def _goto(page, url: str) -> None:
    """Navigate one page; kept small so tests can stub navigation."""
    page.goto(url, wait_until="domcontentloaded", timeout=60_000)


def _is_timeout_error(exc: BaseException) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    if type(exc).__name__ in {"TimeoutError", "PlaywrightTimeoutError"}:
        return True
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    except Exception:  # pragma: no cover - playwright is a runtime dependency
        return False
    return isinstance(exc, PlaywrightTimeoutError)


def _is_retryable(exc: BaseException) -> bool:
    return (
        isinstance(exc, _BlockedPageError)
        or _is_timeout_error(exc)
        or "ERR_CONNECTION_RESET" in str(exc)
    )


def _is_chrome_missing(exc: BaseException) -> bool:
    text = str(exc).lower()
    if "chrome" not in text:
        return False
    markers = (
        "not found",
        "missing",
        "doesn't exist",
        "does not exist",
        "no such file",
        "executable",
    )
    return any(marker in text for marker in markers)


def _pace_asin_load() -> None:
    """Sleep so consecutive ASIN loads start at least MIN_GAP_SEC apart."""
    global _last_load_monotonic
    now = time.monotonic()
    if _last_load_monotonic is not None:
        remaining = MIN_GAP_SEC - (now - _last_load_monotonic)
        if remaining > 0:
            time.sleep(remaining)
            now = time.monotonic()
    _last_load_monotonic = now


def _check_failure_cap(asin: str) -> None:
    if _consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
        raise AmazonUnreachable(
            "AMAZON_UNREACHABLE: failure cap reached after "
            f"{_consecutive_failures} consecutive terminal failures; "
            f"refusing ASIN {asin}"
        )


def _record_terminal_failure() -> None:
    global _consecutive_failures
    _consecutive_failures += 1


def _record_success() -> None:
    global _consecutive_failures
    _consecutive_failures = 0

_PDP_EXTRACT_JS = """
() => {
  const title = document.querySelector('#productTitle')?.textContent?.trim() || '';
  const priceEl =
    document.querySelector('#corePrice_feature_div span.a-price span.a-offscreen')
    || document.querySelector('#corePriceDisplay_desktop_feature_div span.a-price span.a-offscreen')
    || document.querySelector('span.a-price.aok-align-center span.a-offscreen')
    || document.querySelector('#priceblock_ourprice, #priceblock_dealprice')
    || document.querySelector('span.a-offscreen');
  const starsEl = document.querySelector('#acrPopover span.a-icon-alt, i.a-icon-star span.a-icon-alt');
  const reviewsEl = document.querySelector('#acrCustomerReviewText');
  const avail = document.querySelector('#availability')?.innerText || '';
  const variationHint = document.querySelector('#inline-twister-row, #twister, #variation_size_name, #variation_color_name');
  const dimLabels = Array.from(document.querySelectorAll('#twister .a-form-label, #twister .dimension-text, #inline-twister-row .a-button-text'))
    .map(e => e.textContent.trim()).filter(Boolean).slice(0, 8);
  const imgs = [];
  const seen = new Set();
  for (const img of document.querySelectorAll('#altImages img, #imgTagWrapperId img, #landingImage, #main-image-container img')) {
    let src = img.getAttribute('data-old-hires') || img.getAttribute('data-a-dynamic-image') || img.getAttribute('src') || '';
    if (src.startsWith('{')) {
      try {
        const keys = Object.keys(JSON.parse(src));
        src = keys[0] || '';
      } catch (e) { src = ''; }
    }
    if (!src || src.includes('sprite') || src.includes('grey-pixel')) continue;
    src = src.replace(/\\._[A-Z0-9,_]+_\\./, '.');
    if (seen.has(src)) continue;
    seen.add(src);
    imgs.push(src);
    if (imgs.length >= 8) break;
  }
  const children = [];
  const seenKids = new Set();
  const twisterRoot = document.querySelector('#twister, #inline-twister-row, #twister_feature_div, #twister-plus-inline-twister, #variation_size_name');
  if (twisterRoot) {
    for (const el of twisterRoot.querySelectorAll('[data-defaultasin], [data-asin]')) {
      const kid = (el.getAttribute('data-defaultasin') || el.getAttribute('data-asin') || '').toUpperCase();
      if (!/^[A-Z0-9]{10}$/.test(kid) || seenKids.has(kid)) continue;
      seenKids.add(kid);
      const label = (el.getAttribute('title') || el.textContent || '').replace(/\\s+/g, ' ').trim();
      children.push({ asin: kid, label });
    }
  }
  return {
    title,
    price: priceEl ? priceEl.textContent.trim() : null,
    stars: starsEl ? starsEl.textContent.trim() : null,
    reviews: reviewsEl ? reviewsEl.textContent.trim() : null,
    availability: avail,
    has_variations: !!variationHint || children.length > 1,
    variation_labels: dimLabels,
    image_urls: imgs,
    children,
  };
}
"""


def fetch_product_offer(asin: str) -> OfferIn:
    """Load https://www.amazon.de/dp/{asin} and parse offer fields."""
    offer, _html, _raw = _load_pdp(asin)
    return offer


def _load_pdp(asin: str) -> tuple[OfferIn, str, dict[str, Any]]:
    asin = asin.strip().upper()
    if len(asin) != 10:
        raise ValueError("ASIN must be 10 characters")

    _check_failure_cap(asin)
    _pace_asin_load()

    url = f"https://www.amazon.de/dp/{asin}"
    last_exc: BaseException | None = None
    for attempt in range(1, MAX_FETCH_ATTEMPTS + 1):
        try:
            result = _load_pdp_once(asin, url)
        except AsinNotFound:
            # Terminal ASIN classification, not a network failure: one attempt,
            # no sleep, and the consecutive-failure counter is left untouched.
            raise
        except ChromeNotFound:
            # A missing Chrome installation is systemic, not an ASIN failure.
            raise
        except Exception as exc:  # noqa: BLE001 - classified below
            retryable = _is_retryable(exc)
            if retryable and attempt < MAX_FETCH_ATTEMPTS:
                last_exc = exc
                time.sleep(_BACKOFF_BASE_SEC + random.uniform(0.0, _BACKOFF_JITTER_SEC))
                continue

            _record_terminal_failure()
            if retryable:
                raise AmazonUnreachable(
                    f"AMAZON_UNREACHABLE: ASIN {asin} failed after {attempt} attempts; "
                    f"last error {type(exc).__name__}: {exc}"
                ) from exc
            raise
        else:
            _record_success()
            return result

    # Defensive fallback: the loop normally returns or raises above.
    _record_terminal_failure()
    raise AmazonUnreachable(
        f"AMAZON_UNREACHABLE: ASIN {asin} failed after {MAX_FETCH_ATTEMPTS} attempts; "
        f"last error {type(last_exc).__name__ if last_exc is not None else 'UnknownError'}: "
        f"{last_exc}"
    )


def _load_pdp_once(asin: str, url: str) -> tuple[OfferIn, str, dict[str, Any]]:
    """One launch/navigate/parse attempt; fresh logged-out context every time."""
    with _playwright() as p:
        try:
            browser = _launch_browser(p)
        except Exception as exc:  # noqa: BLE001 - Chrome detection needs text
            if _is_chrome_missing(exc):
                raise ChromeNotFound(
                    "CHROME_NOT_FOUND: unable to launch the installed Chrome channel: "
                    f"{type(exc).__name__}: {exc}"
                ) from exc
            raise

        try:
            context = browser.new_context(
                locale="de-DE",
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
            )
            page = context.new_page()
            _goto(page, url)
            html = page.content()
            if _looks_like_not_found_page(html):
                raise AsinNotFound(
                    f"ASIN_NOT_FOUND: {asin} — Amazon reports the product page "
                    "does not exist or was delisted"
                )
            if _looks_like_captcha(html):
                raise RuntimeError("CAPTCHA on product page — try again later")
            if _looks_like_blocked_page(html):
                raise _BlockedPageError(
                    "blocked_page: Amazon returned a short page without "
                    f'id="productTitle" ({len(html)} chars)'
                )
            raw: dict[str, Any] = page.evaluate(_PDP_EXTRACT_JS) or {}
        finally:
            try:
                browser.close()
            except Exception:  # noqa: BLE001 - never mask the real fetch error
                pass

    return _offer_from_raw(asin, url, raw), html, raw


def _offer_from_raw(asin: str, url: str, raw: dict[str, Any]) -> OfferIn:
    price = parse_price_text(str(raw.get("price") or ""))
    if price is None:
        raise RuntimeError("Could not parse product price from Amazon page")

    stars = parse_stars_text(str(raw.get("stars") or ""))
    reviews = parse_reviews_text(str(raw.get("reviews") or ""))
    avail = str(raw.get("availability") or "").lower()
    in_stock = "nicht verfügbar" not in avail and "currently unavailable" not in avail

    note = ""
    if raw.get("has_variations"):
        labels = raw.get("variation_labels") or []
        note = (
            "This ASIN has variations (size/color). Price is for the selected/default child only. "
            + ("Options seen: " + "; ".join(str(x) for x in labels[:6]) if labels else "")
        )

    return OfferIn(
        title=str(raw.get("title") or "").strip(),
        amazon_total=price,
        asin=asin,
        url=url,
        stars=stars,
        reviews=reviews,
        in_stock=in_stock,
        price_source="pdp",
        note=note.strip(),
        sold_by_amazon=False,
        seller_country=None,
        image_urls=[str(u) for u in (raw.get("image_urls") or []) if u],
        parent_asin="",
        variation_label="",
    )


def fetch_variation_offers(
    asin: str,
    *,
    max_children: int = MAX_VARIATION_CHILDREN,
    pause_sec: float = _CHILD_PAUSE_SEC,
) -> list[OfferIn]:
    """Load the PDP; if Amazon has size/color children, fetch each child's price."""
    asin = asin.strip().upper()
    parent, children, html = _fetch_pdp_bundle(asin)
    kids = _children_from_pdp(html, asin, children)
    if not kids:
        return [parent]

    offers: list[OfferIn] = []
    for kid in kids[: max(1, max_children)]:
        if kid.asin == asin:
            offer = parent.model_copy(
                update={
                    "parent_asin": asin,
                    "variation_label": kid.label,
                    "title": apply_variation_label(parent.title, kid.label),
                }
            )
        else:
            time.sleep(max(0.0, pause_sec))
            try:
                offer = fetch_product_offer(kid.asin)
            except Exception:  # noqa: BLE001
                continue
            offer = offer.model_copy(
                update={
                    "parent_asin": asin,
                    "variation_label": kid.label,
                    "title": apply_variation_label(offer.title, kid.label),
                    "stars": offer.stars if offer.stars is not None else parent.stars,
                    "reviews": offer.reviews if offer.reviews is not None else parent.reviews,
                }
            )
        offers.append(offer)
    return offers or [parent]


def _children_from_pdp(
    html: str, current_asin: str, js_children: list[dict[str, Any]]
) -> list[VariationChild]:
    parsed = parse_variation_children(html, current_asin=current_asin)
    if parsed:
        return parsed
    found: dict[str, str] = {}
    for row in js_children:
        child_asin = str(row.get("asin") or "").strip().upper()
        if len(child_asin) != 10:
            continue
        found[child_asin] = str(row.get("label") or "").strip()
    kids = [VariationChild(asin=a, label=found[a]) for a in found]
    return kids if len(kids) > 1 else []


def _fetch_pdp_bundle(asin: str) -> tuple[OfferIn, list[dict[str, Any]], str]:
    offer, html, raw = _load_pdp(asin)
    kids = raw.get("children") if isinstance(raw.get("children"), list) else []
    return offer, [x for x in kids if isinstance(x, dict)], html


def _looks_like_captcha(html: str) -> bool:
    low = html.lower()
    return "captcha" in low or "/errors/validatecaptcha" in low or "robot check" in low


def _looks_like_not_found_page(html: str) -> bool:
    """True when the document's <title> reports a missing/delisted product.

    Amazon.de returns a short "Seite wurde nicht gefunden" page for an ASIN
    that does not exist or was delisted.  That is a terminal ASIN verdict, not
    a transient network/block failure, so it must never be retried.
    """
    for match in _TITLE_RE.finditer(html):
        title = match.group(1).lower()
        if any(marker in title for marker in _NOT_FOUND_TITLE_MARKERS):
            return True
    return False


def _looks_like_blocked_page(html: str) -> bool:
    """A tiny document without the PDP title node is an interstitial/block page.

    A full-size page with a title but no buy box is a genuine no-price page and
    must not be retried as if Amazon were unreachable.  A not-found page is
    terminal and is classified before this helper, never as a block page.
    """
    if _looks_like_not_found_page(html):
        return False
    return len(html) < _BLOCK_PAGE_MAX_CHARS and not _PRODUCT_TITLE_RE.search(html)
