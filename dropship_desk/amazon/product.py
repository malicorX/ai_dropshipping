"""Fetch a single amazon.de product detail page (PDP) for accurate price."""

from __future__ import annotations

import time
from typing import Any

from dropship_desk.amazon.serp import parse_price_text, parse_reviews_text, parse_stars_text
from dropship_desk.models import OfferIn

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
  return {
    title,
    price: priceEl ? priceEl.textContent.trim() : null,
    stars: starsEl ? starsEl.textContent.trim() : null,
    reviews: reviewsEl ? reviewsEl.textContent.trim() : null,
    availability: avail,
    has_variations: !!variationHint,
    variation_labels: dimLabels,
    image_urls: imgs,
  };
}
"""


def fetch_product_offer(asin: str) -> OfferIn:
    """Load https://www.amazon.de/dp/{asin} and parse offer fields."""
    asin = asin.strip().upper()
    if len(asin) != 10:
        raise ValueError("ASIN must be 10 characters")

    from playwright.sync_api import sync_playwright

    url = f"https://www.amazon.de/dp/{asin}"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            locale="de-DE",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        time.sleep(1.5)
        html = page.content()
        if _looks_like_captcha(html):
            browser.close()
            raise RuntimeError("CAPTCHA on product page — try again later")
        raw: dict[str, Any] = page.evaluate(_PDP_EXTRACT_JS)
        browser.close()

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
            + ("Options seen: " + "; ".join(labels[:6]) if labels else "")
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
    )


def _looks_like_captcha(html: str) -> bool:
    low = html.lower()
    return "captcha" in low or "/errors/validatecaptcha" in low or "robot check" in low
