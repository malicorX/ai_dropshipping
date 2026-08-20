from dropship_desk.db import init_db, list_candidates, save_listing_draft, upsert_candidate
from dropship_desk.ebay import listing as ebay_listing
from dropship_desk.ebay.listing import _inventory_description
from dropship_desk.ebay.taxonomy import pick_aspect_value
from dropship_desk.safety import check_ebay_sell


def test_pick_aspect_prefers_markenlos():
    value = pick_aspect_value(
        {
            "localizedAspectName": "Marke",
            "aspectConstraint": {"aspectRequired": True, "aspectMode": "SELECTION_ONLY"},
            "aspectValues": [
                {"localizedValue": "Nike"},
                {"localizedValue": "Markenlos"},
            ],
        }
    )
    assert value == "Markenlos"


def test_pick_aspect_free_text_brand():
    value = pick_aspect_value(
        {
            "localizedAspectName": "Brand",
            "aspectConstraint": {"aspectRequired": True},
            "aspectValues": [],
        }
    )
    assert value == "Markenlos"


def test_ensure_brand_mpn_adds_pair():
    from dropship_desk.ebay.taxonomy import ensure_brand_mpn

    out = ensure_brand_mpn({"Farbe": ["Schwarz"]})
    assert out["Marke"] == ["Markenlos"]
    assert out["Herstellernummer"] == ["Nicht zutreffend"]


def test_sandbox_sell_allowed_without_flags(monkeypatch):
    monkeypatch.setenv("EBAY_ENV", "sandbox")
    monkeypatch.delenv("EBAY_AUTOMATION_ENABLED", raising=False)
    monkeypatch.delenv("EBAY_ALLOW_LIST", raising=False)
    assert check_ebay_sell().ok is True


def test_production_sell_requires_flags(monkeypatch):
    monkeypatch.setenv("EBAY_ENV", "production")
    monkeypatch.delenv("EBAY_AUTOMATION_ENABLED", raising=False)
    monkeypatch.delenv("EBAY_ALLOW_LIST", raising=False)
    assert check_ebay_sell().ok is False
    monkeypatch.setenv("EBAY_AUTOMATION_ENABLED", "true")
    assert check_ebay_sell().ok is False
    monkeypatch.setenv("EBAY_ALLOW_LIST", "true")
    assert check_ebay_sell().ok is True


class _FakeEbay:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def __call__(self, method: str, path: str, **kwargs):
        self.calls.append((method, path))
        if "get_opted_in_programs" in path:
            return {"programs": [{"programType": "SELLING_POLICY_MANAGEMENT"}]}
        if method == "GET" and path == "/sell/inventory/v1/location":
            return {"locations": [{"merchantLocationKey": "dropship_desk"}]}
        if method == "GET" and path == "/sell/account/v1/payment_policy":
            return {"paymentPolicies": [{"paymentPolicyId": "pay-1"}]}
        if method == "GET" and path == "/sell/account/v1/return_policy":
            return {"returnPolicies": [{"returnPolicyId": "ret-1"}]}
        if method == "GET" and path == "/sell/account/v1/fulfillment_policy":
            return {"fulfillmentPolicies": [{"fulfillmentPolicyId": "ful-1"}]}
        if "get_default_category_tree_id" in path:
            return {"categoryTreeId": "77"}
        if "get_category_suggestions" in path:
            return {
                "categorySuggestions": [
                    {"category": {"categoryId": "57991", "categoryName": "Widgets"}}
                ]
            }
        if "get_item_aspects_for_category" in path:
            return {"aspects": []}
        if method == "PUT" and "/sell/inventory/v1/inventory_item/" in path:
            return None
        if method == "GET" and path == "/sell/inventory/v1/offer":
            return {"offers": []}
        if method == "POST" and path == "/sell/inventory/v1/offer":
            return {"offerId": "OFFER-99"}
        if method == "POST" and path.endswith("/publish"):
            return {"listingId": "1234567890"}
        raise AssertionError(f"unexpected eBay call {method} {path}")


def _seed_draft(tmp_path, monkeypatch):
    import dropship_desk.config as cfg

    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cfg, "DB_PATH", tmp_path / "dropship.sqlite3")
    monkeypatch.setenv("EBAY_ENV", "sandbox")
    init_db()
    upsert_candidate(
        asin="B0TESTASI1",
        title="Test Widget",
        amazon_total=20.0,
        ebay_price=55.0,
        max_amazon_buy=20.0,
        status="drafted",
        offer={"asin": "B0TESTASI1"},
        margin={"passed": True},
        hard_reject=[],
    )
    save_listing_draft(
        "B0TESTASI1",
        {
            "title": "Praktisches Test Widget fuer den Alltag",
            "description_html": "<p>Beschreibung</p>",
            "bullet_points": ["Eins", "Zwei"],
        },
    )


def test_stage_unpublished_then_publish(tmp_path, monkeypatch):
    _seed_draft(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "dropship_desk.ebay.listing.pictures.collect_image_urls",
        lambda asin, draft: ["https://i.ebayimg.com/00/s/fake.jpg"],
    )
    monkeypatch.setattr(
        "dropship_desk.ebay.taxonomy.ebay_oauth.application_token",
        lambda: "app-token",
    )
    fake = _FakeEbay()
    staged = ebay_listing.stage_unpublished("B0TESTASI1", http=fake)
    assert staged["status"] == "unpublished"
    assert staged["offer_id"] == "OFFER-99"
    assert staged.get("item_url") in ("", None)
    rows = list_candidates(status="pipeline")
    assert rows[0]["status"] == "ebay_unpublished"

    published = ebay_listing.publish_offer("B0TESTASI1", http=fake)
    assert published["status"] == "published"
    assert published["listing_id"] == "1234567890"
    assert "/itm/1234567890" in published["item_url"]
    assert list_candidates(status="pipeline")[0]["status"] == "listed"


def test_stage_api_requires_oauth(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import dropship_desk.config as cfg
    from dropship_desk.api import create_app

    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cfg, "DB_PATH", tmp_path / "dropship.sqlite3")
    client = TestClient(create_app())
    r = client.post("/api/ebay/listings/B0TESTASI1/stage", json={})
    assert r.status_code == 400


def test_production_stage_forbidden_without_flags(tmp_path, monkeypatch):
    import json

    from fastapi.testclient import TestClient

    import dropship_desk.config as cfg
    from dropship_desk.api import create_app

    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cfg, "DB_PATH", tmp_path / "dropship.sqlite3")
    monkeypatch.setenv("EBAY_ENV", "production")
    monkeypatch.delenv("EBAY_AUTOMATION_ENABLED", raising=False)
    monkeypatch.delenv("EBAY_ALLOW_LIST", raising=False)
    (tmp_path / "ebay_oauth_production.json").write_text(
        json.dumps({"refresh_token": "r", "access_token": "a"}),
        encoding="utf-8",
    )
    client = TestClient(create_app())
    r = client.post("/api/ebay/listings/B0TESTASI1/stage", json={})
    assert r.status_code == 403


def test_inventory_description_stays_under_4000():
    bullets = [f"Punkt {i} " + ("x" * 200) for i in range(20)]
    html = _inventory_description("Titel", bullets)
    assert 1 <= len(html) <= 4000
    assert "Titel" in html
