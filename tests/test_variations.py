from dropship_desk.amazon.variations import apply_variation_label, parse_variation_children
from dropship_desk.db import get_candidate_by_asin, upsert_candidate
from dropship_desk.models import OfferIn
from dropship_desk.variation_expand import persist_variation_offers


def test_parse_twister_dimension_json():
    html = """
    <script>
    var config = {
      "dimensionValuesDisplayData": {
        "B0CHLD20KG": ["20 kg", "Schwarz"],
        "B0CHLD40KG": ["40 kg", "Schwarz"]
      }
    };
    </script>
    """
    kids = parse_variation_children(html, current_asin="B0PARENT000")
    asins = {c.asin: c.label for c in kids}
    assert asins["B0CHLD20KG"] == "20 kg / Schwarz"
    assert asins["B0CHLD40KG"] == "40 kg / Schwarz"


def test_single_asin_is_not_a_parent():
    html = '{"dimensionValuesDisplayData":{"B0ONLYCHLD":["20 kg"]}}'
    assert parse_variation_children(html, current_asin="B0ONLYCHLD") == []


def test_apply_variation_label_skips_duplicate():
    assert apply_variation_label("Hantelset 20 kg", "20 kg") == "Hantelset 20 kg"
    assert apply_variation_label("Hantelset", "20 kg") == "Hantelset — 20 kg"


def test_persist_splits_parent_into_children(tmp_path, monkeypatch):
    import dropship_desk.config as cfg

    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cfg, "DB_PATH", tmp_path / "dropship.sqlite3")
    monkeypatch.setenv("EBAY_ENV", "sandbox")

    upsert_candidate(
        asin="B0PARENT000",
        title="Hantelset parent",
        amazon_total=19.99,
        ebay_price=49.99,
        max_amazon_buy=19.99,
        status="ready",
        offer={"asin": "B0PARENT000", "amazon_total": 19.99, "price_source": "serp"},
        margin={"passed": True},
        hard_reject=[],
    )
    offers = [
        OfferIn(
            title="Hantelset — 20 kg",
            amazon_total=22.0,
            asin="B0CHLD20KG",
            url="https://www.amazon.de/dp/B0CHLD20KG",
            stars=4.6,
            reviews=200,
            price_source="pdp",
            parent_asin="B0PARENT000",
            variation_label="20 kg",
            in_stock=True,
            seller_country="CN",
        ),
        OfferIn(
            title="Hantelset — 40 kg",
            amazon_total=39.0,
            asin="B0CHLD40KG",
            url="https://www.amazon.de/dp/B0CHLD40KG",
            stars=4.6,
            reviews=200,
            price_source="pdp",
            parent_asin="B0PARENT000",
            variation_label="40 kg",
            in_stock=True,
            seller_country="CN",
        ),
    ]
    out = persist_variation_offers("B0PARENT000", offers)
    assert out.expanded is True
    parent = get_candidate_by_asin("B0PARENT000")
    assert parent is not None
    assert parent["status"] == "rejected"
    assert any("variation parent" in r for r in parent["hard_reject_reasons"])
    child = get_candidate_by_asin("B0CHLD20KG")
    assert child is not None
    assert child["offer"]["variation_label"] == "20 kg"
    assert child["amazon_total"] == 22.0


def test_persist_from_child_does_not_reject_that_child(tmp_path, monkeypatch):
    import dropship_desk.config as cfg

    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cfg, "DB_PATH", tmp_path / "dropship.sqlite3")
    offers = [
        OfferIn(
            title="Hantelset — 20 kg",
            amazon_total=22.0,
            asin="B0CHLD20KG",
            url="https://www.amazon.de/dp/B0CHLD20KG",
            price_source="pdp",
            variation_label="20 kg",
            in_stock=True,
            seller_country="CN",
        ),
        OfferIn(
            title="Hantelset — 40 kg",
            amazon_total=39.0,
            asin="B0CHLD40KG",
            url="https://www.amazon.de/dp/B0CHLD40KG",
            price_source="pdp",
            variation_label="40 kg",
            in_stock=True,
            seller_country="CN",
        ),
    ]
    out = persist_variation_offers("B0CHLD20KG", offers, persist="always")
    assert out.expanded is True
    twenty = get_candidate_by_asin("B0CHLD20KG")
    assert twenty is not None
    assert twenty["status"] != "rejected"
    assert twenty["offer"]["variation_label"] == "20 kg"
