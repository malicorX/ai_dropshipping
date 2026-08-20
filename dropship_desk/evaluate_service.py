"""Shared evaluate pipeline used by API and Find job."""

from __future__ import annotations

from typing import Literal

from dropship_desk.asin import extract_asin, hard_reject_reasons
from dropship_desk.db import get_candidate_by_asin, get_margin_settings, upsert_candidate
from dropship_desk.margin import MarginInputs, evaluate_margin, suggest_ebay_price
from dropship_desk.models import EvaluateRequest, EvaluateResponse, OfferIn

PersistMode = Literal["always", "pass_only", "never"]


def run_evaluate(
    body: EvaluateRequest,
    *,
    persist: PersistMode | None = None,
) -> EvaluateResponse:
    settings = get_margin_settings()
    if body.offer is None:
        raise ValueError("offer required")
    offer = body.offer
    asin = (
        extract_asin(body.asin_or_url)
        or extract_asin(offer.asin)
        or offer.asin
        or "UNKNOWN"
    )
    asin = asin.strip().upper()

    rejects = hard_reject_reasons(offer, settings)
    suggested = suggest_ebay_price(
        offer.amazon_total,
        fee_pct=settings.ebay_fee_pct,
        fee_fixed=settings.ebay_fee_fixed,
        buffer_eur=settings.buffer_eur,
        min_margin_eur=settings.min_margin_eur,
        min_margin_pct=settings.min_margin_pct,
    )
    ebay_price = body.ebay_price if body.ebay_price is not None else suggested
    max_buy = (
        body.max_amazon_buy if body.max_amazon_buy is not None else offer.amazon_total
    )
    margin = evaluate_margin(
        MarginInputs(
            amazon_total=offer.amazon_total,
            ebay_price=ebay_price,
            ebay_fee_pct=settings.ebay_fee_pct,
            ebay_fee_fixed=settings.ebay_fee_fixed,
            buffer_eur=settings.buffer_eur,
            min_margin_eur=settings.min_margin_eur,
            min_margin_pct=settings.min_margin_pct,
        )
    )
    passed = margin.passed and not rejects
    status = "ready" if passed else "rejected"
    margin_dict = {
        "ebay_fees": margin.ebay_fees,
        "net_proceeds": margin.net_proceeds,
        "net_profit": margin.net_profit,
        "margin_pct": margin.margin_pct,
        "passed": margin.passed,
        "fail_reasons": list(margin.fail_reasons),
    }

    mode: PersistMode
    if persist is not None:
        mode = persist
    elif not body.save:
        mode = "never"
    else:
        mode = "always"

    candidate_id = None
    should_write = mode == "always" or (mode == "pass_only" and passed)
    if mode == "pass_only" and not passed and get_candidate_by_asin(asin):
        # Refresh existing row if a former PASS now fails.
        should_write = True

    if should_write:
        candidate_id = upsert_candidate(
            asin=asin,
            title=offer.title,
            amazon_total=offer.amazon_total,
            ebay_price=ebay_price,
            max_amazon_buy=max_buy,
            status=status,
            offer=offer.model_dump(),
            margin=margin_dict,
            hard_reject=rejects,
        )

    stored_status = status
    if candidate_id is not None:
        existing = get_candidate_by_asin(asin)
        if existing:
            stored_status = existing["status"]

    return EvaluateResponse(
        asin=asin,
        offer=offer,
        ebay_price=ebay_price,
        max_amazon_buy=max_buy,
        suggested_ebay_price=suggested,
        passed=passed,
        hard_reject_reasons=rejects,
        margin=margin_dict,
        candidate_id=candidate_id,
        status=stored_status,
    )


def offer_from_serp(
    *,
    asin: str,
    title: str,
    price: float,
    url: str,
    stars: float | None = None,
    reviews: int | None = None,
) -> OfferIn:
    return OfferIn(
        title=title,
        amazon_total=price,
        asin=asin,
        url=url,
        stars=stars,
        reviews=reviews,
        in_stock=True,
        sold_by_amazon=False,
        seller_country=None,
        price_source="serp",
        note="SERP snapshot — may be rounded or a different variation; refresh from product page before listing.",
    )
