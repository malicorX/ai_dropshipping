"""Plain callable behind POST /api/listing/generate.

The FastAPI endpoint and the upload-items background job share this pipeline so
the listing copy, image download and artifact behaviour cannot drift apart.
"""

from __future__ import annotations

from typing import Any

from dropship_desk import config
from dropship_desk.amazon.product import fetch_variation_offers
from dropship_desk.db import (
    get_candidate_by_asin,
    patch_candidate_offer,
    save_listing_draft,
)
from dropship_desk.evaluate_service import run_evaluate
from dropship_desk.models import EvaluateRequest, OfferIn
from dropship_desk.ollama_client import generate_listing_draft, ollama_reachable
from dropship_desk.product_media import download_product_images, save_draft_artifacts
from dropship_desk.variation_expand import persist_variation_offers


class ListingGenerateError(RuntimeError):
    """A domain failure the API maps back to its historical HTTP response."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class VariationParentError(ListingGenerateError):
    """The ASIN is an Amazon variation parent, not a sellable child."""

    def __init__(self, detail: str) -> None:
        super().__init__(400, detail)


def generate_draft(
    asin: str | None,
    ebay_price: float | None = None,
    amazon_total: float | None = None,
    title: str | None = None,
    force_refresh_images: bool = False,
    *,
    offer: OfferIn | None = None,
    evaluate: bool = True,
) -> dict[str, Any]:
    """Create unique eBay copy via Ollama (not a 1:1 Amazon clone).

    ``offer``/``evaluate`` are supplied by the upload-items worker after it has
    already fetched the PDP and run the margin gate; the HTTP endpoint leaves
    them at their defaults and therefore keeps its original behaviour.
    """
    asin = str(asin or "").strip().upper()
    if len(asin) != 10:
        raise ListingGenerateError(400, "asin required (10 chars)")
    if not ollama_reachable():
        raise ListingGenerateError(
            503,
            f"Ollama unreachable at {config.OLLAMA_BASE_URL}",
        )

    row = get_candidate_by_asin(asin)
    amazon_title = str(title or (row["title"] if row else "") or "")
    if amazon_total is None and row:
        amazon_total = row["amazon_total"]
    if ebay_price is None and row:
        ebay_price = row["ebay_price"]
    if amazon_total is None or ebay_price is None:
        raise ListingGenerateError(400, "amazon_total and ebay_price required")

    image_urls: list[str] = []
    offer_data = (row or {}).get("offer") or {}
    image_urls = list(offer_data.get("image_urls") or [])
    variation_label = str(offer_data.get("variation_label") or "")
    facts_bullets = list(offer_data.get("bullets") or [])
    facts_specs = dict(offer_data.get("specs") or {})

    if offer is not None:
        facts_bullets = list(offer.bullets or facts_bullets)
        facts_specs = dict(offer.specs or facts_specs)
        picked = offer
        amazon_title = picked.title or amazon_title
        amazon_total = picked.amazon_total
        image_urls = picked.image_urls or image_urls
        variation_label = picked.variation_label or variation_label
        if variation_label and variation_label.lower() not in amazon_title.lower():
            amazon_title = f"{amazon_title} — {variation_label}"
        if evaluate:
            run_evaluate(
                EvaluateRequest(
                    asin_or_url=asin,
                    offer=picked.model_copy(
                        update={
                            "title": amazon_title,
                            "variation_label": variation_label,
                        }
                    ),
                    ebay_price=float(ebay_price),
                    save=True,
                ),
                persist="always",
            )
    else:
        try:
            offers = fetch_variation_offers(asin)
            child_asins = {o.asin.strip().upper() for o in offers}
            if len(offers) > 1 and asin not in child_asins:
                persist_variation_offers(asin, offers, persist="pass_only")
                labels = ", ".join(
                    f"{(o.variation_label or o.asin)} ({o.asin})" for o in offers
                )
                raise VariationParentError(
                    "This Amazon page is a variation parent (e.g. 20 kg vs 40 kg). "
                    f"Split into: {labels}. Generate the listing from a child in Queue — "
                    "do not publish the parent ASIN."
                )
            picked = next((o for o in offers if o.asin.strip().upper() == asin), offers[0])
            facts_bullets = list(picked.bullets or facts_bullets)
            facts_specs = dict(picked.specs or facts_specs)
            amazon_title = picked.title or amazon_title
            amazon_total = picked.amazon_total
            image_urls = picked.image_urls or image_urls
            variation_label = picked.variation_label or variation_label
            if variation_label and variation_label.lower() not in amazon_title.lower():
                amazon_title = f"{amazon_title} — {variation_label}"
            run_evaluate(
                EvaluateRequest(
                    asin_or_url=asin,
                    offer=picked.model_copy(
                        update={
                            "title": amazon_title,
                            "variation_label": variation_label,
                        }
                    ),
                    ebay_price=float(ebay_price),
                    save=True,
                ),
                persist="always",
            )
        except ListingGenerateError:
            raise
        except Exception:  # noqa: BLE001 - historical endpoint swallowed PDP refresh errors
            pass

    media = download_product_images(
        asin,
        image_urls,
        force=force_refresh_images,
    )
    patch_candidate_offer(
        asin,
        {
            "image_urls": media.get("source_urls") or image_urls,
            "local_images": media.get("local_images") or [],
        },
    )

    try:
        draft = generate_listing_draft(
            amazon_title=amazon_title,
            asin=asin,
            amazon_price=float(amazon_total),
            ebay_price=float(ebay_price),
            image_urls=image_urls,
            bullets=facts_bullets,
            specs=facts_specs,
            bullets_hint=(
                f"Variante/Größe/Farbe: {variation_label}. "
                "Nur DIESE Variante beschreiben; Geschwistergrößen nicht erwähnen."
                if variation_label
                else ""
            ),
        )
    except Exception as e:  # noqa: BLE001
        raise ListingGenerateError(502, f"LLM generate failed: {e}") from e

    artifacts = save_draft_artifacts(asin, draft, media)
    draft["artifacts"] = artifacts
    draft["media"] = {
        "local_images": media.get("local_images") or [],
        "source_urls": media.get("source_urls") or [],
        "download_errors": media.get("errors") or [],
    }

    if row or get_candidate_by_asin(asin):
        save_listing_draft(asin, draft)
    return {"draft": draft, "asin": asin, "media": media, "artifacts": artifacts}
