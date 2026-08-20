"""Pydantic request/response models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class OfferIn(BaseModel):
    title: str = ""
    amazon_total: float
    currency: str = "EUR"
    in_stock: bool = True
    delivery_days: int | None = None
    seller_country: str | None = None
    sold_by_amazon: bool = False
    asin: str = ""
    url: str = ""
    stars: float | None = None
    reviews: int | None = None
    price_source: str = ""  # "serp" | "pdp" | "manual"
    note: str = ""
    image_urls: list[str] = Field(default_factory=list)
    local_images: list[dict[str, Any]] = Field(default_factory=list)


class EvaluateRequest(BaseModel):
    asin_or_url: str = ""
    ebay_price: float | None = None
    max_amazon_buy: float | None = None
    offer: OfferIn | None = None
    save: bool = True


class MarginSettings(BaseModel):
    ebay_fee_pct: float = 0.15
    ebay_fee_fixed: float = 0.35
    buffer_eur: float = 3.0
    min_margin_eur: float = 5.0
    min_margin_pct: float = 0.50
    max_delivery_days: int = 10
    min_stock: int = 10
    skip_sold_by_amazon: bool = True
    reject_dach_sellers: bool = True


class ListingShopSettings(BaseModel):
    """Shop footer copy — same on every listing; edit in Settings."""

    shop_name: str = "Dropship Desk Shop"
    accent_color: str = "#0f6e56"
    shipping_html: str = (
        "<ul>"
        "<li><strong>Versand innerhalb Deutschlands:</strong> In der Regel "
        "3–7 Werktage nach Versand. Abweichungen durch Lieferanten möglich.</li>"
        "<li><strong>Sendungsverfolgung:</strong> Soweit verfügbar, teilen wir "
        "die Tracking-Informationen über eBay mit.</li>"
        "<li><strong>Bearbeitung:</strong> Bestellungen werden werktags zügig "
        "weitergeleitet (typisch 1–2 Werktage nach Zahlungseingang).</li>"
        "<li><strong>Hinweis:</strong> Lieferungen auf deutsche Inseln und in "
        "besonders abgelegene Gebiete können länger dauern oder eingeschränkt sein.</li>"
        "</ul>"
    )
    returns_html: str = (
        "<ul>"
        "<li><strong>30-Tage Rückgaberecht:</strong> Gesetzliches Widerrufsrecht "
        "für Verbraucher (Details in den Angebotsbedingungen).</li>"
        "<li><strong>Ablauf:</strong> Bitte zuerst über eBay-Nachrichten Kontakt "
        "aufnehmen — wir klären den Rücksendeweg mit Ihnen.</li>"
        "<li><strong>Zustand:</strong> Rückgabe in originalem, unbenutztem Zustand "
        "mit vollständigem Zubehör.</li>"
        "<li><strong>Kosten:</strong> Bei Widerruf trägt der Käufer in der Regel "
        "die Rücksendekosten, sofern nicht anders vereinbart oder gesetzlich anders geregelt.</li>"
        "</ul>"
    )
    payment_html: str = (
        "<ul>"
        "<li><strong>Zahlung:</strong> Über die von eBay angebotenen "
        "Zahlungsmethoden (z.&nbsp;B. PayPal, Karte — je nach Angebot).</li>"
        "<li><strong>Abwicklung:</strong> Zahlung läuft über eBay. Bitte innerhalb "
        "weniger Tage nach Kauf abschließen, damit der Versand starten kann.</li>"
        "</ul>"
    )
    feedback_html: str = (
        "<p>Ihr Feedback ist uns wichtig. Wenn Sie zufrieden sind, freuen wir uns "
        "über eine positive Bewertung. Bei Fragen oder Problemen schreiben Sie uns "
        "<strong>bitte zuerst über eBay-Nachrichten</strong>, bevor Sie negatives "
        "Feedback hinterlassen — wir suchen gemeinsam eine Lösung.</p>"
    )
    contact_html: str = (
        "<p>Kontakt ausschließlich über das <strong>eBay-Nachrichtensystem</strong>. "
        "Wir antworten in der Regel Mo–Sa, 9:00–18:00 Uhr.</p>"
    )
    photo_disclaimer_html: str = (
        "<p class=\"dd-note\">Hinweis zu den Fotos: Abbildungen dienen der "
        "Produktdarstellung und können im Detail (z.&nbsp;B. Farbe, Zubehör) leicht "
        "vom gelieferten Artikel abweichen.</p>"
    )


class DiscoverySettings(BaseModel):
    keyword: str = ""
    auto_mode: bool = False
    min_stars: float = 4.4
    min_reviews: int = 50
    price_min_eur: float = 10.0
    price_max_eur: float = 200.0
    skip_sponsored: bool = True
    hit_target: int = 20
    max_search_pages: int = 5
    pause_ms: int = 1500


class EvaluateResponse(BaseModel):
    asin: str
    offer: OfferIn
    ebay_price: float
    max_amazon_buy: float
    suggested_ebay_price: float
    passed: bool
    hard_reject_reasons: list[str]
    margin: dict[str, Any]
    candidate_id: int | None = None
    status: str


class SettingsOut(BaseModel):
    margin: MarginSettings
    listing_shop: ListingShopSettings = Field(default_factory=ListingShopSettings)
    ollama_base_url: str
    ollama_model: str
    discovery_defaults: DiscoverySettings = Field(default_factory=DiscoverySettings)


class SettingsIn(BaseModel):
    margin: MarginSettings | None = None
    listing_shop: ListingShopSettings | None = None


class OpenExternalRequest(BaseModel):
    url: str
