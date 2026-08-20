from dropship_desk.db import upsert_candidate
from dropship_desk.reprice import reprice_candidates


def test_reprice_applies_new_margin(tmp_path, monkeypatch):
    import dropship_desk.config as cfg
    from dropship_desk.db import set_margin_settings
    from dropship_desk.models import MarginSettings

    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cfg, "DB_PATH", tmp_path / "dropship.sqlite3")

    set_margin_settings(MarginSettings(min_margin_pct=0.50, min_margin_eur=5.0))
    upsert_candidate(
        asin="B0REPRICE01",
        title="Old price row",
        amazon_total=30.0,
        ebay_price=46.99,  # old 20%-era suggestion
        max_amazon_buy=30.0,
        status="ready",
        offer={"asin": "B0REPRICE01", "amazon_total": 30.0, "title": "Old price row"},
        margin={"passed": True},
        hard_reject=[],
    )
    out = reprice_candidates(status="ready")
    assert out["updated"] == 1
    assert out["details"][0]["new_ebay"] > 46.99
    assert out["details"][0]["new_ebay"] >= 56.0
