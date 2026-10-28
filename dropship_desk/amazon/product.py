"""Fetch a single amazon.de product detail page (PDP) for accurate price."""

from __future__ import annotations

import random
import re
import threading
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
CAP_COOLDOWN_SEC = 600.0
MAX_FETCH_ATTEMPTS = 3
_BACKOFF_BASE_SEC = 5.0
_BACKOFF_JITTER_SEC = 1.0
_BLOCK_PAGE_MAX_CHARS = 20_000
_FAILURE_CAP_PREFIX = "AMAZON_UNREACHABLE: failure cap reached"
_PRODUCT_TITLE_RE = re.compile(r"""id\s*=\s*["']productTitle["']""", re.IGNORECASE)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_NOT_FOUND_TITLE_MARKERS = ("seite wurde nicht gefunden", "page not found")

# One process-wide fetch at a time: pacing, the failure cap and its counter
# must be read/modified atomically.  RLock keeps a nested child fetch (should
# one ever be issued from inside _load_pdp) from deadlocking.
_FETCH_LOCK = threading.RLock()

_last_load_monotonic: float | None = None
_consecutive_failures = 0
_last_terminal_failure_monotonic: float | None = None


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
    global _last_terminal_failure_monotonic
    _last_load_monotonic = None
    _consecutive_failures = 0
    _last_terminal_failure_monotonic = None


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
    """Refuse fetches while the cap is open; half-open after the cooldown.

    The cap is not a permanent lockout: once CAP_COOLDOWN_SEC has elapsed since
    the last terminal failure, the counter is lowered to
    MAX_CONSECUTIVE_FAILURES - 1 and one probe attempt is allowed.  A successful
    probe resets the counter; a failed probe increments it straight back to the
    cap and stamps a fresh failure time, re-opening the breaker for another full
    cooldown.
    """
    global _consecutive_failures, _last_terminal_failure_monotonic
    if _consecutive_failures < MAX_CONSECUTIVE_FAILURES:
        return

    now = time.monotonic()
    last_failure = _last_terminal_failure_monotonic
    if last_failure is None or now - last_failure >= CAP_COOLDOWN_SEC:
        # Half-open: leave exactly one failure's worth of headroom.  A probe
        # success resets this to 0; a terminal probe failure takes it back to
        # MAX_CONSECUTIVE_FAILURES and re-arms a fresh cooldown timestamp.
        _consecutive_failures = MAX_CONSECUTIVE_FAILURES - 1
        _last_terminal_failure_monotonic = None
        return

    raise AmazonUnreachable(
        f"{_FAILURE_CAP_PREFIX} after "
        f"{_consecutive_failures} consecutive terminal failures; "
        f"refusing ASIN {asin}"
    )


def _record_terminal_failure() -> None:
    global _consecutive_failures, _last_terminal_failure_monotonic
    _consecutive_failures += 1
    _last_terminal_failure_monotonic = time.monotonic()


def _record_success() -> None:
    global _consecutive_failures, _last_terminal_failure_monotonic
    _consecutive_failures = 0
    _last_terminal_failure_monotonic = None

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
  const clean = (t) => (t || '').replace(/[\\u200e\\u200f]/g, '').replace(/\\s+/g, ' ').trim();
  const bullets = Array.from(document.querySelectorAll('#feature-bullets li span.a-list-item, #feature-bullets li'))
    .map(e => clean(e.textContent)).filter(t => t && t.length > 3).slice(0, 12);
  const specs = {};
  const addSpec = (k, v) => {
    k = clean(k).replace(/[:：]$/, '').trim(); v = clean(v);
    if (k && v && k.length < 60 && !(k in specs)) specs[k] = v.slice(0, 300);
  };
  for (const row of document.querySelectorAll(
    '#productOverview_feature_div tr, #productDetails_techSpec_section_1 tr, ' +
    '#productDetails_techSpec_section_2 tr, #productDetails_detailBullets_sections1 tr, ' +
    '#technicalSpecifications_section_1 tr')) {
    const th = row.querySelector('th, td:first-child');
    const td = row.querySelector('td:last-child');
    if (th && td && th !== td) addSpec(th.textContent, td.textContent);
  }
  for (const li of document.querySelectorAll('#detailBullets_feature_div li')) {
    const parts = clean(li.textContent).split(/\\s*[:：]\\s*/);
    if (parts.length >= 2) addSpec(parts[0], parts.slice(1).join(': '));
  }
  return {
    title,
    bullets,
    specs,
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

    url = f"https://www.amazon.de/dp/{asin}"
    # Hold the lock across cap check, pacing and every retry: launches from
    # concurrent threads must never overlap or observe a half-updated counter.
    with _FETCH_LOCK:
        _check_failure_cap(asin)
        _pace_asin_load()

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
        bullets=[str(b) for b in (raw.get("bullets") or []) if b],
        specs={str(k): str(v) for k, v in (raw.get("specs") or {}).items()},
    )


class VariationOfferList(list[OfferIn]):
    """Offer list that also records whether the PDP advertised variations.

    A plain list loses the difference between "not a variation page" and
    "variation page whose children could not be fetched" — both fall back to
    the parent snapshot.  The upload job uses this metadata to reject the
    latter as a variation parent.
    """

    def __init__(
        self,
        offers: list[OfferIn],
        *,
        reported_variations: bool,
        children_fetched: int,
    ) -> None:
        super().__init__(offers)
        self.reported_variations = reported_variations
        self.children_fetched = children_fetched


def fetch_variation_offers(
    asin: str,
    *,
    max_children: int = MAX_VARIATION_CHILDREN,
    pause_sec: float = _CHILD_PAUSE_SEC,
) -> VariationOfferList:
    """Load the PDP; if Amazon has size/color children, fetch each child's price."""
    asin = asin.strip().upper()
    parent, children, html, raw = _fetch_pdp_bundle(asin)
    page_reports_variations = bool(raw.get("has_variations"))
    kids = _children_from_pdp(html, asin, children)
    if not kids:
        return VariationOfferList(
            [parent],
            reported_variations=page_reports_variations,
            children_fetched=0,
        )

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
            except ChromeNotFound:
                # A missing browser is systemic: surface it instead of silently
                # returning a partial variation list.
                raise
            except AmazonUnreachable as exc:
                if str(exc).startswith(_FAILURE_CAP_PREFIX):
                    # The process-wide cap tripped; do not keep hammering Amazon.
                    raise
                # An unreachable child is a per-ASIN failure: skip just it.
                continue
            except Exception:  # noqa: BLE001 - not-found/parse errors are per-child
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
    return VariationOfferList(
        offers or [parent],
        reported_variations=True,
        children_fetched=len(offers),
    )


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


def _fetch_pdp_bundle(
    asin: str,
) -> tuple[OfferIn, list[dict[str, Any]], str, dict[str, Any]]:
    offer, html, raw = _load_pdp(asin)
    kids = raw.get("children") if isinstance(raw.get("children"), list) else []
    return offer, [x for x in kids if isinstance(x, dict)], html, raw


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
