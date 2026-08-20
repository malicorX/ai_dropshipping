from dropship_desk.db import upsert_candidate
from dropship_desk.enrich import enrich_missing
from dropship_desk.models import OfferIn


def test_enrich_fills_missing_stars(tmp_path, monkeypatch):
    import dropship_desk.config as cfg

    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cfg, "DB_PATH", tmp_path / "dropship.sqlite3")

    upsert_candidate(
        asin="B0ENRICH001",
        title="No stars yet",
        amazon_total=40.0,
        ebay_price=74.99,
        max_amazon_buy=40.0,
        status="ready",
        offer={
            "asin": "B0ENRICH001",
            "amazon_total": 40.0,
            "title": "No stars yet",
            "price_source": "serp",
            "stars": None,
            "reviews": None,
        },
        margin={"passed": True},
        hard_reject=[],
    )

    def fake_fetch(asin: str) -> OfferIn:
        return OfferIn(
            title="Enriched title",
            amazon_total=38.0,
            asin=asin,
            url=f"https://www.amazon.de/dp/{asin}",
            stars=4.7,
            reviews=120,
            price_source="pdp",
            in_stock=True,
        )

    monkeypatch.setattr("dropship_desk.enrich.fetch_product_offer", fake_fetch)
    monkeypatch.setattr("dropship_desk.enrich.time.sleep", lambda _s: None)

    out = enrich_missing(limit=5, status="ready", pause_sec=0)
    assert out["targeted"] == 1
    assert out["updated"] == 1
    assert out["details"][0]["stars"] == 4.7
    assert out["details"][0]["reviews"] == 120

    from dropship_desk.db import get_candidate_by_asin

    row = get_candidate_by_asin("B0ENRICH001")
    assert row is not None
    assert row["offer"]["stars"] == 4.7
    assert row["offer"]["price_source"] == "pdp"
