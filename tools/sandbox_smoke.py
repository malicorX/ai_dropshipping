"""Sandbox smoke test: upload ONE synthetic article to the connected eBay *sandbox* account.

Never touches production: the target is forced to sandbox and the script refuses to run
if the API host is not api.sandbox.ebay.com. No Amazon data, no DB candidate needed.

  python tools/sandbox_smoke.py --status           # what is configured / connected
  python tools/sandbox_smoke.py --switch-account   # park old sandbox tokens, then reconnect via the app
  python tools/sandbox_smoke.py                    # stage + publish + read back
  python tools/sandbox_smoke.py --no-publish       # stop at the unpublished offer
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dropship_desk import config  # noqa: E402
from dropship_desk.ebay import account_setup, client as ebay_http, oauth, taxonomy  # noqa: E402

SKU = "DD-SMOKE-TEST-1"
TITLE = "Dropship Desk Sandbox Testartikel Keramik Tasse weiss 300 ml"
DEFAULT_IMAGE = "https://upload.wikimedia.org/wikipedia/commons/thumb/4/45/A_small_cup_of_coffee.JPG/640px-A_small_cup_of_coffee.JPG"


def force_sandbox() -> None:
    config.set_ebay_env_override("sandbox")
    if config.ebay_api_base() != "https://api.sandbox.ebay.com":
        raise SystemExit("REFUSED: API base is not the eBay sandbox host")


def status() -> dict:
    return {
        "env": config.ebay_env(),
        "api_base": config.ebay_api_base(),
        "config_gaps": config.ebay_target_gaps("sandbox"),
        "oauth_connected": oauth.oauth_connected("sandbox"),
    }


def switch_account() -> list[str]:
    """Park the old sandbox user's token + account cache so the next connect is a fresh login."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    parked = []
    for path in (oauth.token_path_for("sandbox"), config.DATA_DIR / "ebay_account_sandbox.json"):
        if path.is_file():
            target = path.with_name(path.name + f".old-{stamp}")
            path.rename(target)
            parked.append(target.name)
    return parked


def run(*, publish: bool, image_url: str, http=None) -> dict:
    requester = http or ebay_http.request
    force_sandbox()
    setup = account_setup.ensure_seller_setup(http=requester)
    category = taxonomy.suggest_category(TITLE, http=requester)
    aspects = taxonomy.aspects_for_category(category["category_id"], category["tree_id"], http=requester)
    brand, mpn = taxonomy.brand_mpn_fields(aspects)
    requester(
        "PUT",
        f"/sell/inventory/v1/inventory_item/{SKU}",
        json_body={
            "availability": {"shipToLocationAvailability": {"quantity": 1}},
            "condition": "NEW",
            "product": {
                "title": TITLE,
                "description": "<p>Sandbox smoke test, not a real product.</p>",
                "aspects": aspects,
                "imageUrls": [image_url],
                "brand": brand,
                "mpn": mpn,
            },
        },
    )
    payload = {
        "sku": SKU,
        "marketplaceId": ebay_http.MARKETPLACE_ID,
        "format": "FIXED_PRICE",
        "listingDescription": "<p>Sandbox smoke test, not a real product.</p>",
        "availableQuantity": 1,
        "categoryId": category["category_id"],
        "merchantLocationKey": setup["merchant_location_key"],
        "listingDuration": "GTC",
        "pricingSummary": {"price": {"value": "9.99", "currency": "EUR"}},
        "listingPolicies": {
            "fulfillmentPolicyId": setup["fulfillment_policy_id"],
            "paymentPolicyId": setup["payment_policy_id"],
            "returnPolicyId": setup["return_policy_id"],
        },
    }
    try:
        offers = (requester("GET", "/sell/inventory/v1/offer", params={"sku": SKU}) or {}).get("offers") or []
    except ebay_http.EbayApiError as e:
        if e.status_code not in (400, 404):
            raise
        offers = []
    if offers:
        offer_id = str(offers[0]["offerId"])
        requester("PUT", f"/sell/inventory/v1/offer/{offer_id}", json_body=payload)
    else:
        offer_id = str((requester("POST", "/sell/inventory/v1/offer", json_body=payload) or {}).get("offerId") or "")
    if not offer_id:
        raise RuntimeError("createOffer returned no offerId")
    result = {"sku": SKU, "offer_id": offer_id, "status": "unpublished", "listing_id": "", "item_url": ""}
    if publish:
        data = requester("POST", f"/sell/inventory/v1/offer/{offer_id}/publish") or {}
        listing_id = str(data.get("listingId") or "")
        result.update(status="published", listing_id=listing_id, item_url=f"https://www.sandbox.ebay.com/itm/{listing_id}")
        back = requester("GET", f"/sell/inventory/v1/offer/{offer_id}") or {}
        result["remote_status"] = back.get("status")
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--switch-account", action="store_true")
    ap.add_argument("--no-publish", action="store_true")
    ap.add_argument("--image-url", default=DEFAULT_IMAGE)
    a = ap.parse_args()
    force_sandbox()
    if a.status:
        print(json.dumps(status(), indent=2))
        return 0
    if a.switch_account:
        print(json.dumps({"parked": switch_account(), **status()}, indent=2))
        print("Next: start the app, Settings -> Sandbox -> Connect sandbox eBay, log in with the NEW sandbox user.")
        return 0
    st = status()
    if st["config_gaps"] or not st["oauth_connected"]:
        print(json.dumps(st, indent=2))
        print("NOT READY: fill the gaps in .env and/or connect the sandbox account in the app first.")
        return 2
    print(json.dumps(run(publish=not a.no_publish, image_url=a.image_url), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
