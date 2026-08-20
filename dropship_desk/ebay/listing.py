"""Draft → unpublished Inventory offer → explicit publish."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Callable

from dropship_desk import config
from dropship_desk.db import get_candidate_by_asin, save_ebay_listing, save_listing_draft
from dropship_desk.ebay import account_setup, client as ebay_http, pictures, taxonomy
from dropship_desk.product_media import product_dir, save_draft_artifacts

HttpFn = Callable[..., Any]

SKU_PREFIX = "DD-"
DEFAULT_QUANTITY = 5


def sku_for_asin(asin: str) -> str:
    return f"{SKU_PREFIX}{asin.strip().upper()}"


def listing_state_path(asin: str):
    return product_dir(asin) / f"ebay_{config.ebay_env()}.json"


def load_listing_state(asin: str) -> dict[str, Any]:
    path = listing_state_path(asin)
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_listing_state(asin: str, state: dict[str, Any]) -> dict[str, Any]:
    record = dict(state)
    record["env"] = config.ebay_env()
    record["updated_at"] = datetime.now(timezone.utc).isoformat()
    record.setdefault("sku", sku_for_asin(asin))
    record["seller_hub_url"] = seller_hub_url(record.get("status") or "")
    record["item_url"] = item_url(str(record.get("listing_id") or ""))
    listing_state_path(asin).write_text(json.dumps(record, indent=2), encoding="utf-8")
    save_ebay_listing(asin, record)
    return record


def seller_hub_url(status: str) -> str:
    """Browser page worth opening. Sandbox My eBay selling lists are broken; use the item URL after publish."""
    if config.ebay_env() == "production":
        if status == "published":
            return "https://www.ebay.de/sh/lst/active"
        return "https://www.ebay.de/sh/lst/draft"
    return ""


def item_url(listing_id: str) -> str:
    if not listing_id:
        return ""
    if config.ebay_env() == "production":
        return f"https://www.ebay.de/itm/{listing_id}"
    return f"https://www.sandbox.ebay.com/itm/{listing_id}"


def public_listing(asin: str) -> dict[str, Any]:
    state = load_listing_state(asin)
    if not state:
        return {
            "asin": asin.strip().upper(),
            "env": config.ebay_env(),
            "status": "none",
            "sku": sku_for_asin(asin),
            "offer_id": "",
            "listing_id": "",
            "item_url": "",
            "seller_hub_url": seller_hub_url(""),
            "category_id": "",
            "category_name": "",
            "error": "",
        }
    listing = {"asin": asin.strip().upper(), **state}
    listing["seller_hub_url"] = seller_hub_url(str(listing.get("status") or ""))
    listing["item_url"] = item_url(str(listing.get("listing_id") or ""))
    return listing


def stage_unpublished(
    asin: str,
    draft_patch: dict[str, Any] | None = None,
    *,
    http: HttpFn | None = None,
) -> dict[str, Any]:
    """Create/replace inventory item + unpublished offer. Does not publish."""
    requester = http or ebay_http.request
    asin = asin.strip().upper()
    row = get_candidate_by_asin(asin)
    if not row:
        raise RuntimeError("No candidate for this ASIN — Analyze margin first")
    draft = dict(row.get("listing_draft") or {})
    if draft_patch:
        for key in ("title", "subtitle", "description_html", "bullet_points"):
            if key in draft_patch and draft_patch[key] is not None:
                draft[key] = draft_patch[key]
    if not str(draft.get("title") or "").strip():
        raise RuntimeError("Generate a listing draft first")
    price = float(row["ebay_price"])
    if price <= 0:
        raise RuntimeError("eBay price must be > 0")

    title = _clip(str(draft.get("title") or ""), 80)
    description = str(draft.get("description_html") or "").strip()
    if not description:
        bullets = draft.get("bullet_points") or []
        items = "".join(f"<li>{_escape(b)}</li>" for b in bullets)
        description = f"<p>{_escape(title)}</p><ul>{items}</ul>"
    inventory_description = _inventory_description(
        title, draft.get("bullet_points") or []
    )

    save_listing_draft(asin, draft)
    save_draft_artifacts(asin, draft, draft.get("media"))

    setup = account_setup.ensure_seller_setup(http=requester)
    category = taxonomy.suggest_category(title, http=requester)
    aspects = taxonomy.aspects_for_category(
        category["category_id"], category["tree_id"], http=requester
    )
    brand, mpn = taxonomy.brand_mpn_fields(aspects)
    image_urls = pictures.collect_image_urls(asin, draft)
    if not image_urls:
        raise RuntimeError("No product images to send (download images when generating the draft)")

    sku = sku_for_asin(asin)
    quantity = DEFAULT_QUANTITY
    requester(
        "PUT",
        f"/sell/inventory/v1/inventory_item/{sku}",
        json_body={
            "availability": {"shipToLocationAvailability": {"quantity": quantity}},
            "condition": "NEW",
            "product": {
                "title": title,
                "description": inventory_description,
                "aspects": aspects,
                "imageUrls": image_urls,
                "brand": brand,
                "mpn": mpn,
            },
        },
    )

    offer_payload = {
        "sku": sku,
        "marketplaceId": ebay_http.MARKETPLACE_ID,
        "format": "FIXED_PRICE",
        "listingDescription": description,
        "availableQuantity": quantity,
        "quantityLimitPerBuyer": 2,
        "categoryId": category["category_id"],
        "merchantLocationKey": setup["merchant_location_key"],
        "listingDuration": "GTC",
        "pricingSummary": {"price": {"value": f"{price:.2f}", "currency": "EUR"}},
        "listingPolicies": {
            "fulfillmentPolicyId": setup["fulfillment_policy_id"],
            "paymentPolicyId": setup["payment_policy_id"],
            "returnPolicyId": setup["return_policy_id"],
        },
    }
    offer_id = _create_or_update_offer(sku, offer_payload, http=requester)
    save_listing_state(
        asin,
        {
            "status": "unpublished",
            "sku": sku,
            "offer_id": offer_id,
            "listing_id": "",
            "category_id": category["category_id"],
            "category_name": category.get("category_name") or "",
            "price": price,
            "image_count": len(image_urls),
            "error": "",
        },
    )
    return public_listing(asin)


def publish_offer(asin: str, *, http: HttpFn | None = None) -> dict[str, Any]:
    """Convert an unpublished offer into a live (sandbox or production) listing."""
    requester = http or ebay_http.request
    asin = asin.strip().upper()
    state = load_listing_state(asin)
    offer_id = str(state.get("offer_id") or "")
    if not offer_id:
        raise RuntimeError("No unpublished offer yet — send the draft to eBay first")
    if state.get("status") == "published" and state.get("listing_id"):
        return public_listing(asin)
    data = requester("POST", f"/sell/inventory/v1/offer/{offer_id}/publish") or {}
    listing_id = str(data.get("listingId") or "")
    save_listing_state(
        asin,
        {
            **state,
            "status": "published",
            "listing_id": listing_id,
            "error": "",
        },
    )
    return public_listing(asin)


def _create_or_update_offer(sku: str, payload: dict[str, Any], *, http: HttpFn) -> str:
    existing = _offer_id_for_sku(sku, http=http)
    if existing:
        http("PUT", f"/sell/inventory/v1/offer/{existing}", json_body=payload)
        return existing
    created = http("POST", "/sell/inventory/v1/offer", json_body=payload) or {}
    offer_id = str(created.get("offerId") or "")
    if not offer_id:
        raise RuntimeError("eBay createOffer returned no offerId")
    return offer_id


def _offer_id_for_sku(sku: str, *, http: HttpFn) -> str:
    try:
        data = http("GET", "/sell/inventory/v1/offer", params={"sku": sku}) or {}
    except ebay_http.EbayApiError as e:
        if e.status_code in (400, 404):
            return ""
        raise
    offers = data.get("offers") or []
    if not offers:
        return ""
    return str(offers[0].get("offerId") or "")


def _clip(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _inventory_description(title: str, bullets: list[Any]) -> str:
    """Inventory item description is capped at 4000 chars; full HTML goes on the offer."""
    items = "".join(f"<li>{_escape(b)}</li>" for b in bullets[:8] if str(b).strip())
    html = f"<p>{_escape(title)}</p>"
    if items:
        html += f"<ul>{items}</ul>"
    return _clip(html, 4000)


def _escape(value: Any) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
