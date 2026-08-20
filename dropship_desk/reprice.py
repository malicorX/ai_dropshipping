"""Reprice stored candidates with current margin settings."""

from __future__ import annotations

from typing import Any

from dropship_desk.db import get_margin_settings, list_candidates, upsert_candidate
from dropship_desk.margin import MarginInputs, evaluate_margin, suggest_ebay_price
from dropship_desk.models import OfferIn


def reprice_candidates(*, status: str | None = None, limit: int = 500) -> dict[str, Any]:
    """
    Recalculate suggested eBay prices from stored amazon_total using current Settings.
    Does not hit Amazon. Updates margin + ready/rejected (listed/drafted stay protected in upsert).
    """
    settings = get_margin_settings()
    rows = list_candidates(limit=limit, status=status)
    updated = 0
    now_ready = 0
    now_rejected = 0
    details: list[dict[str, Any]] = []

    for row in rows:
        amazon_total = float(row["amazon_total"])
        if amazon_total <= 0:
            continue
        suggested = suggest_ebay_price(
            amazon_total,
            fee_pct=settings.ebay_fee_pct,
            fee_fixed=settings.ebay_fee_fixed,
            buffer_eur=settings.buffer_eur,
            min_margin_eur=settings.min_margin_eur,
            min_margin_pct=settings.min_margin_pct,
        )
        margin = evaluate_margin(
            MarginInputs(
                amazon_total=amazon_total,
                ebay_price=suggested,
                ebay_fee_pct=settings.ebay_fee_pct,
                ebay_fee_fixed=settings.ebay_fee_fixed,
                buffer_eur=settings.buffer_eur,
                min_margin_eur=settings.min_margin_eur,
                min_margin_pct=settings.min_margin_pct,
            )
        )
        offer_raw = row.get("offer") or {}
        offer = OfferIn.model_validate(
            {
                **offer_raw,
                "title": row["title"] or offer_raw.get("title") or "",
                "amazon_total": amazon_total,
                "asin": row["asin"],
            }
        )
        hard = list(row.get("hard_reject_reasons") or [])
        passed = margin.passed and not hard
        new_status = "ready" if passed else "rejected"
        if passed:
            now_ready += 1
        else:
            now_rejected += 1

        upsert_candidate(
            asin=row["asin"],
            title=offer.title,
            amazon_total=amazon_total,
            ebay_price=suggested,
            max_amazon_buy=float(row.get("max_amazon_buy") or amazon_total),
            status=new_status,
            offer=offer.model_dump(),
            margin={
                "ebay_fees": margin.ebay_fees,
                "net_proceeds": margin.net_proceeds,
                "net_profit": margin.net_profit,
                "margin_pct": margin.margin_pct,
                "passed": margin.passed,
                "fail_reasons": list(margin.fail_reasons),
            },
            hard_reject=hard,
        )
        updated += 1
        details.append(
            {
                "asin": row["asin"],
                "amazon_total": amazon_total,
                "old_ebay": row["ebay_price"],
                "new_ebay": suggested,
                "status": new_status,
            }
        )

    return {
        "updated": updated,
        "ready": now_ready,
        "rejected": now_rejected,
        "min_margin_pct": settings.min_margin_pct,
        "min_margin_eur": settings.min_margin_eur,
        "details": details[:50],
    }
