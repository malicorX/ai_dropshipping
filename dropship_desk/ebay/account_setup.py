"""Ensure inventory location + business policies for EBAY_DE."""

from __future__ import annotations

import json
from typing import Any

from dropship_desk import config
from dropship_desk.ebay import client as ebay_http

MERCHANT_LOCATION_KEY = "dropship_desk"
POLICY_NAME_PREFIX = "Dropship Desk"


def _account_env(env: str | None = None) -> str:
    return config.normalize_ebay_env(
        env if env is not None else config.operation_env()
    )


def account_cache_path(env: str | None = None):
    config.ensure_data_dir()
    return config.DATA_DIR / f"ebay_account_{_account_env(env)}.json"


def load_account_cache(env: str | None = None) -> dict[str, Any]:
    path = account_cache_path(env)
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_account_cache(data: dict[str, Any], env: str | None = None) -> None:
    account_cache_path(env).write_text(json.dumps(data, indent=2), encoding="utf-8")


def ensure_seller_setup(*, http=ebay_http.request, env: str | None = None) -> dict[str, str]:
    """Return merchantLocationKey + policy IDs, creating them if the account has none."""
    target = _account_env(env)
    # Account setup is one operation: the cache path and every derived request
    # stay on the env captured here even if the target flips mid-setup.
    with config.ebay_operation(target) as request_env:
        return _ensure_seller_setup(http=http, env=request_env)


def _ensure_seller_setup(*, http, env: str) -> dict[str, str]:
    ensure_business_policy_opt_in(http=http)
    cached = load_account_cache(env)
    location_key = ensure_inventory_location(http=http)
    payment_id = _first_policy_id(
        http, "/sell/account/v1/payment_policy", "paymentPolicies", "paymentPolicyId"
    ) or cached.get("payment_policy_id")
    if not payment_id:
        created = http(
            "POST",
            "/sell/account/v1/payment_policy",
            json_body={
                "name": f"{POLICY_NAME_PREFIX} Zahlung",
                "marketplaceId": ebay_http.MARKETPLACE_ID,
                "categoryTypes": [
                    {"name": "ALL_EXCLUDING_MOTORS_VEHICLES", "default": True}
                ],
                "immediatePay": True,
            },
        )
        payment_id = str((created or {}).get("paymentPolicyId") or "")
    return_id = _first_policy_id(
        http, "/sell/account/v1/return_policy", "returnPolicies", "returnPolicyId"
    ) or cached.get("return_policy_id")
    if not return_id:
        created = http(
            "POST",
            "/sell/account/v1/return_policy",
            json_body={
                "name": f"{POLICY_NAME_PREFIX} Rueckgabe",
                "marketplaceId": ebay_http.MARKETPLACE_ID,
                "categoryTypes": [
                    {"name": "ALL_EXCLUDING_MOTORS_VEHICLES", "default": True}
                ],
                "returnsAccepted": True,
                "returnPeriod": {"value": 30, "unit": "DAY"},
                "refundMethod": "MONEY_BACK",
                "returnShippingCostPayer": "BUYER",
            },
        )
        return_id = str((created or {}).get("returnPolicyId") or "")
    fulfill_id = _first_policy_id(
        http,
        "/sell/account/v1/fulfillment_policy",
        "fulfillmentPolicies",
        "fulfillmentPolicyId",
    ) or cached.get("fulfillment_policy_id")
    if not fulfill_id:
        fulfill_id = _create_fulfillment_policy(http)
    if not payment_id or not return_id or not fulfill_id:
        raise RuntimeError(
            "Could not create or find eBay business policies "
            f"(payment={bool(payment_id)}, return={bool(return_id)}, "
            f"fulfillment={bool(fulfill_id)})"
        )
    record = {
        "merchant_location_key": location_key,
        "payment_policy_id": payment_id,
        "return_policy_id": return_id,
        "fulfillment_policy_id": fulfill_id,
    }
    save_account_cache(record, env=env)
    return record


def ensure_business_policy_opt_in(*, http=ebay_http.request) -> None:
    """Inventory offers need SELLING_POLICY_MANAGEMENT. Sandbox accounts start opted out."""
    try:
        data = http("GET", "/sell/account/v1/program/get_opted_in_programs") or {}
    except ebay_http.EbayApiError:
        data = {}
    types = {
        str(row.get("programType") or "")
        for row in (data.get("programs") or [])
        if isinstance(row, dict)
    }
    if "SELLING_POLICY_MANAGEMENT" in types:
        return
    try:
        http(
            "POST",
            "/sell/account/v1/program/opt_in",
            json_body={"programType": "SELLING_POLICY_MANAGEMENT"},
        )
        return
    except ebay_http.EbayApiError as e:
        if e.status_code != 404:
            raise
    http(
        "POST",
        "/sell/account/v1/program/opt_in_to_program",
        json_body={"programType": "SELLING_POLICY_MANAGEMENT"},
    )


def ensure_inventory_location(*, http=ebay_http.request) -> str:
    try:
        data = http("GET", "/sell/inventory/v1/location") or {}
    except ebay_http.EbayApiError as e:
        if e.status_code not in (400, 404, 500):
            raise
        data = {}
    locations = data.get("locations") or []
    for loc in locations:
        key = str(loc.get("merchantLocationKey") or "")
        if key:
            return key
    try:
        http(
            "POST",
            f"/sell/inventory/v1/location/{MERCHANT_LOCATION_KEY}",
            json_body={
                "name": "Dropship Desk",
                "merchantLocationStatus": "ENABLED",
                "locationTypes": ["WAREHOUSE"],
                "location": {
                    "address": {
                        "addressLine1": "Invalidenstrasse 1",
                        "city": "Berlin",
                        "country": "DE",
                        "postalCode": "10115",
                    }
                },
            },
        )
    except ebay_http.EbayApiError as e:
        if e.status_code not in (400, 409):
            raise
    return MERCHANT_LOCATION_KEY


def _first_policy_id(http, path: str, list_key: str, id_key: str) -> str:
    try:
        data = http("GET", path, params={"marketplace_id": ebay_http.MARKETPLACE_ID}) or {}
    except ebay_http.EbayApiError as e:
        if e.status_code not in (400, 404, 500):
            raise
        data = {}
    rows = data.get(list_key) or []
    for row in rows:
        pid = str(row.get(id_key) or "")
        if pid:
            return pid
    return ""


def _create_fulfillment_policy(http) -> str:
    last_error = ""
    for service in ("DE_DHLPaket", "DE_Paket", "DE_StandardDelivery"):
        try:
            created = http(
                "POST",
                "/sell/account/v1/fulfillment_policy",
                json_body={
                    "name": f"{POLICY_NAME_PREFIX} Versand {service}",
                    "marketplaceId": ebay_http.MARKETPLACE_ID,
                    "categoryTypes": [
                        {"name": "ALL_EXCLUDING_MOTORS_VEHICLES", "default": True}
                    ],
                    "handlingTime": {"value": 2, "unit": "DAY"},
                    "shippingOptions": [
                        {
                            "optionType": "DOMESTIC",
                            "costType": "FLAT_RATE",
                            "shippingServices": [
                                {
                                    "sortOrder": 1,
                                    "shippingServiceCode": service,
                                    "freeShipping": True,
                                    "shippingCost": {"value": "0.0", "currency": "EUR"},
                                }
                            ],
                        }
                    ],
                },
            )
            pid = str((created or {}).get("fulfillmentPolicyId") or "")
            if pid:
                return pid
        except Exception as e:  # noqa: BLE001
            last_error = str(e)
            continue
    raise RuntimeError(f"Could not create fulfillment policy: {last_error}")
