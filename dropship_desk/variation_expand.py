"""Turn an Amazon parent ASIN into separate child candidates."""

from __future__ import annotations

from dataclasses import dataclass, field

from dropship_desk.db import upsert_candidate
from dropship_desk.evaluate_service import PersistMode, run_evaluate
from dropship_desk.models import EvaluateRequest, EvaluateResponse, OfferIn

PARENT_REJECT = "variation parent — each size/color is stored as its own ASIN"


@dataclass
class ExpandResult:
    parent_asin: str
    expanded: bool
    results: list[EvaluateResponse] = field(default_factory=list)
    child_asins: list[str] = field(default_factory=list)


def persist_variation_offers(
    parent_asin: str,
    offers: list[OfferIn],
    *,
    persist: PersistMode = "pass_only",
) -> ExpandResult:
    parent_asin = parent_asin.strip().upper()
    unique: list[OfferIn] = []
    seen: set[str] = set()
    for offer in offers:
        asin = (offer.asin or "").strip().upper()
        if not asin or asin in seen:
            continue
        seen.add(asin)
        unique.append(offer)

    child_asins = {o.asin.strip().upper() for o in unique}
    expanded = len(unique) > 1
    starting_is_hub = expanded and parent_asin not in child_asins
    if starting_is_hub:
        _reject_parent(parent_asin, unique)

    results: list[EvaluateResponse] = []
    for offer in unique:
        if starting_is_hub and offer.asin.strip().upper() == parent_asin:
            continue
        results.append(
            run_evaluate(
                EvaluateRequest(asin_or_url=offer.asin, offer=offer, save=True),
                persist=persist,
            )
        )
    return ExpandResult(
        parent_asin=parent_asin,
        expanded=expanded,
        results=results,
        child_asins=[o.asin.strip().upper() for o in unique],
    )


def _reject_parent(parent_asin: str, children: list[OfferIn]) -> None:
    sample = next((c for c in children if c.asin.strip().upper() != parent_asin), children[0])
    child_ids = ", ".join(
        c.asin.strip().upper() for c in children if c.asin.strip().upper() != parent_asin
    )
    upsert_candidate(
        asin=parent_asin,
        title=sample.title.split(" — ")[0] if sample.title else parent_asin,
        amazon_total=float(sample.amazon_total or 0),
        ebay_price=0.0,
        max_amazon_buy=float(sample.amazon_total or 0),
        status="rejected",
        offer={
            "asin": parent_asin,
            "title": sample.title,
            "amazon_total": sample.amazon_total,
            "price_source": "pdp",
            "note": PARENT_REJECT,
            "parent_asin": "",
            "variation_label": "",
        },
        margin={"passed": False, "fail_reasons": [PARENT_REJECT]},
        hard_reject=[f"{PARENT_REJECT}: {child_ids}"],
        protect_workflow=False,
    )
