"""eBay category suggestion + required item aspects for EBAY_DE."""

from __future__ import annotations

from typing import Any, Callable

from dropship_desk.ebay import client as ebay_http
from dropship_desk.ebay import oauth as ebay_oauth

HttpFn = Callable[..., Any]

_PREFERRED_ASPECTS = (
    "markenlos",
    "unbranded",
    "generic",
    "ohne marke",
    "nicht zutreffend",
    "does not apply",
    "n/a",
    "unbekannt",
    "siehe beschreibung",
    "siehe artikelbeschreibung",
    "sonstige",
    "other",
)


def suggest_category(title: str, *, http: HttpFn | None = None) -> dict[str, str]:
    query = (title or "").strip()
    if len(query) < 3:
        raise RuntimeError("Need a listing title to pick an eBay category")
    tree_id = _category_tree_id(http=http)
    token = ebay_oauth.application_token()
    requester = http or ebay_http.request
    data = requester(
        "GET",
        f"/commerce/taxonomy/v1/category_tree/{tree_id}/get_category_suggestions",
        params={"q": query[:200]},
        token=token,
    ) or {}
    suggestions = data.get("categorySuggestions") or []
    if not suggestions:
        raise RuntimeError(f"eBay returned no category for: {query[:80]}")
    first = suggestions[0].get("category") or {}
    category_id = str(first.get("categoryId") or "")
    name = str(first.get("categoryName") or "")
    if not category_id:
        raise RuntimeError("eBay category suggestion missing categoryId")
    return {"category_id": category_id, "category_name": name, "tree_id": tree_id}


def aspects_for_category(
    category_id: str,
    tree_id: str,
    *,
    http: HttpFn | None = None,
) -> dict[str, list[str]]:
    requester = http or ebay_http.request
    token = ebay_oauth.application_token()
    data = requester(
        "GET",
        f"/commerce/taxonomy/v1/category_tree/{tree_id}/get_item_aspects_for_category",
        params={"category_id": category_id},
        token=token,
    ) or {}
    filled: dict[str, list[str]] = {}
    extras: dict[str, dict[str, Any]] = {}
    for aspect in data.get("aspects") or []:
        name = str(aspect.get("localizedAspectName") or "").strip()
        if not name:
            continue
        low = name.lower()
        if "marke" in low or low == "brand":
            extras["brand"] = aspect
        if "herstellernummer" in low or low in ("mpn", "manufacturer part number"):
            extras["mpn"] = aspect
        constraint = aspect.get("aspectConstraint") or {}
        if not constraint.get("aspectRequired"):
            continue
        value = pick_aspect_value(aspect)
        if value:
            filled[name] = [value]
    return ensure_brand_mpn(filled, extras)


def ensure_brand_mpn(
    aspects: dict[str, list[str]],
    extras: dict[str, dict[str, Any]] | None = None,
) -> dict[str, list[str]]:
    """eBay publish requires the BrandMPN pair; Marke without MPN is rejected."""
    extras = extras or {}
    out = dict(aspects)
    brand_aspect = extras.get("brand") or {}
    mpn_aspect = extras.get("mpn") or {}
    brand_name = str(brand_aspect.get("localizedAspectName") or "Marke")
    mpn_name = str(mpn_aspect.get("localizedAspectName") or "Herstellernummer")
    if brand_aspect:
        out[brand_name] = [pick_aspect_value(brand_aspect)]
    elif not _aspect_by_hint(out, ("marke", "brand")):
        out[brand_name] = ["Markenlos"]
    if mpn_aspect:
        out[mpn_name] = [pick_aspect_value(mpn_aspect) or "Nicht zutreffend"]
    elif not _aspect_by_hint(out, ("herstellernummer", "mpn")):
        out[mpn_name] = ["Nicht zutreffend"]
    return out


def brand_mpn_fields(aspects: dict[str, list[str]]) -> tuple[str, str]:
    brand = _aspect_by_hint(aspects, ("marke", "brand")) or "Markenlos"
    mpn = _aspect_by_hint(aspects, ("herstellernummer", "mpn")) or "Nicht zutreffend"
    return brand, mpn


def _aspect_by_hint(aspects: dict[str, list[str]], hints: tuple[str, ...]) -> str:
    for name, values in aspects.items():
        low = name.lower()
        if any(h in low for h in hints) and values:
            return str(values[0])
    return ""


def pick_aspect_value(aspect: dict[str, Any]) -> str:
    values = [
        str(v.get("localizedValue") or "").strip()
        for v in (aspect.get("aspectValues") or [])
        if str(v.get("localizedValue") or "").strip()
    ]
    name = str(aspect.get("localizedAspectName") or "").lower()
    for candidate in values:
        if candidate.lower() in _PREFERRED_ASPECTS:
            return candidate
    if values and ("marke" in name or "brand" in name):
        for candidate in values:
            low = candidate.lower()
            if "ohne" in low or "generic" in low or "markenlos" in low:
                return candidate
        return "Markenlos"
    if values:
        constraint = aspect.get("aspectConstraint") or {}
        mode = str(constraint.get("aspectMode") or "")
        if mode == "SELECTION_ONLY":
            return values[0]
        return values[0]
    if "marke" in name or "brand" in name:
        return "Markenlos"
    if "mpn" in name or "herstellernummer" in name:
        return "Nicht zutreffend"
    return "Siehe Beschreibung"


def _category_tree_id(*, http: HttpFn | None = None) -> str:
    requester = http or ebay_http.request
    token = ebay_oauth.application_token()
    data = requester(
        "GET",
        "/commerce/taxonomy/v1/get_default_category_tree_id",
        params={"marketplace_id": ebay_http.MARKETPLACE_ID},
        token=token,
    ) or {}
    tree_id = str(data.get("categoryTreeId") or "")
    if not tree_id:
        raise RuntimeError("Could not resolve eBay DE category tree")
    return tree_id
