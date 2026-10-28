import pytest
from dropship_desk.db import init_db, list_candidates, save_listing_draft, upsert_candidate
from dropship_desk.ebay import listing as ebay_listing
from dropship_desk.ebay.listing import _candidate_ean, _inventory_description
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


def test_seller_hub_hidden_until_published(monkeypatch):
    from dropship_desk.ebay.listing import seller_hub_url

    monkeypatch.setenv("EBAY_ENV", "production")
    assert seller_hub_url("unpublished") == ""
    assert seller_hub_url("published") == "https://www.ebay.de/mys/active"
    monkeypatch.setenv("EBAY_ENV", "sandbox")
    assert seller_hub_url("published") == ""


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
        self.bodies: list[tuple[str, str, dict | None]] = []

    def __call__(self, method: str, path: str, **kwargs):
        self.calls.append((method, path))
        self.bodies.append((method, path, kwargs.get("json_body")))
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


def _seed_draft(
    tmp_path,
    monkeypatch,
    *,
    offer=None,
    title="Praktisches Test Widget fuer den Alltag",
):
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
        offer=offer or {"asin": "B0TESTASI1"},
        margin={"passed": True},
        hard_reject=[],
    )
    save_listing_draft(
        "B0TESTASI1",
        {
            "title": title,
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


def _inventory_put_body(fake: _FakeEbay) -> dict:
    body = next(
        payload
        for method, path, payload in fake.bodies
        if method == "PUT" and "/sell/inventory/v1/inventory_item/" in path
    )
    assert isinstance(body, dict)
    return body


def _stub_stage_io(monkeypatch) -> None:
    monkeypatch.setattr(
        "dropship_desk.ebay.listing.pictures.collect_image_urls",
        lambda asin, draft: ["https://i.ebayimg.com/00/s/fake.jpg"],
    )
    monkeypatch.setattr(
        "dropship_desk.ebay.taxonomy.ebay_oauth.application_token",
        lambda: "app-token",
    )


def test_stage_inventory_item_uses_ean_placeholder(tmp_path, monkeypatch):
    _seed_draft(tmp_path, monkeypatch)
    _stub_stage_io(monkeypatch)
    fake = _FakeEbay()

    ebay_listing.stage_unpublished("B0TESTASI1", http=fake)

    product = _inventory_put_body(fake)["product"]
    assert product["ean"] == ["Nicht zutreffend"]
    # Brand/MPN handling is unchanged.
    assert product["brand"] == "Markenlos"
    assert product["mpn"] == "Nicht zutreffend"


def test_stage_inventory_item_uses_real_candidate_gtin(tmp_path, monkeypatch):
    _seed_draft(
        tmp_path,
        monkeypatch,
        offer={"asin": "B0TESTASI1", "ean": "4006381333931"},
    )
    _stub_stage_io(monkeypatch)
    fake = _FakeEbay()

    ebay_listing.stage_unpublished("B0TESTASI1", http=fake)

    product = _inventory_put_body(fake)["product"]
    assert product["ean"] == ["4006381333931"]


@pytest.mark.parametrize("key", ["ean", "EAN", "gtin", "GTIN"])
@pytest.mark.parametrize(
    "value",
    ["12345678", "123456789012", "4006381333931", "12345678901234"],
)
def test_candidate_ean_accepts_exact_keys_and_valid_gtin_lengths(key, value):
    row = {"offer": {"asin": "B0TESTASI1", key: value}}
    assert _candidate_ean(row) == value


@pytest.mark.parametrize(
    "key", ["ean_code", "my_ean", "meaning_code", "gtin_code", "product_gtin"]
)
def test_candidate_ean_ignores_substring_keys(key):
    row = {"offer": {"asin": "B0TESTASI1", "ean": "", key: "4006381333931"}}
    assert _candidate_ean(row) == ""


def test_candidate_ean_rejects_meaning_code_even_with_13_digits():
    row = {"offer": {"asin": "B0TESTASI1", "meaning_code": "4006381333931"}}
    assert _candidate_ean(row) == ""


@pytest.mark.parametrize(
    "value", ["1234567", "123456789", "1234567890", "12345678901", "123456789012345"]
)
def test_candidate_ean_rejects_gtin_values_of_any_other_length(value):
    row = {"offer": {"asin": "B0TESTASI1", "ean": value}}
    assert _candidate_ean(row) == ""


def test_candidate_ean_reads_nested_aspects():
    row = {
        "offer": {
            "asin": "B0TESTASI1",
            "aspects": {"GTIN": "4006381333931"},
        }
    }
    assert _candidate_ean(row) == "4006381333931"


def test_stage_inventory_item_ignores_meaning_code_and_9_digit_value(
    tmp_path, monkeypatch
):
    _seed_draft(
        tmp_path,
        monkeypatch,
        offer={
            "asin": "B0TESTASI1",
            "meaning_code": "123456789",
            "GTIN": "123456789",
        },
    )
    _stub_stage_io(monkeypatch)
    fake = _FakeEbay()

    ebay_listing.stage_unpublished("B0TESTASI1", http=fake)

    product = _inventory_put_body(fake)["product"]
    # meaning_code is not an EAN key; the 9-digit EAN/GTIN values are invalid.
    assert product["ean"] == ["Nicht zutreffend"]


def test_stage_accepts_variation_label_case_insensitively(tmp_path, monkeypatch):
    # The draft title already carries the label in a different case.  The
    # stage guard must accept it instead of asking for a regeneration.
    _seed_draft(
        tmp_path,
        monkeypatch,
        offer={"asin": "B0TESTASI1", "variation_label": "Red / G2"},
        title="Praktisches Test Widget fuer den Alltag - red / g2",
    )
    _stub_stage_io(monkeypatch)
    fake = _FakeEbay()

    staged = ebay_listing.stage_unpublished("B0TESTASI1", http=fake)

    assert staged["status"] == "unpublished"
    body = _inventory_put_body(fake)
    assert body["product"]["title"].endswith("red / g2")


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


def test_production_stage_requires_confirm_live(tmp_path, monkeypatch):
    import json

    from fastapi.testclient import TestClient

    import dropship_desk.config as cfg
    from dropship_desk.api import create_app

    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cfg, "DB_PATH", tmp_path / "dropship.sqlite3")
    monkeypatch.setenv("EBAY_ENV", "production")
    monkeypatch.setenv("EBAY_AUTOMATION_ENABLED", "true")
    monkeypatch.setenv("EBAY_ALLOW_LIST", "true")
    cfg.clear_live_env_cache()
    (tmp_path / "ebay_oauth_production.json").write_text(
        json.dumps({"refresh_token": "r", "access_token": "a"}),
        encoding="utf-8",
    )
    client = TestClient(create_app())
    r = client.post("/api/ebay/listings/B0TESTASI1/stage", json={})
    # The old single-listing path is closed in production regardless of
    # confirm_live: only the guarded Prepared/upload plan may write.
    assert r.status_code == 403
    assert r.json()["code"] == "LIVE_UPLOAD_DISABLED"
    assert "Prepared" in r.json()["detail"]


def test_target_switch_blocked_without_prod_keys(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import dropship_desk.config as cfg
    from dropship_desk.api import create_app

    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cfg, "DB_PATH", tmp_path / "dropship.sqlite3")
    monkeypatch.delenv("EBAY_PROD_APP_ID", raising=False)
    monkeypatch.delenv("EBAY_PROD_CERT_ID", raising=False)
    monkeypatch.delenv("EBAY_PROD_RUNAME", raising=False)
    client = TestClient(create_app())
    r = client.post("/api/ebay/target", json={"env": "production"})
    assert r.status_code == 400
    assert client.get("/api/health").json()["ebay"]["env"] == "sandbox"


def test_target_switch_persists(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import dropship_desk.config as cfg
    from dropship_desk.api import create_app

    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cfg, "DB_PATH", tmp_path / "dropship.sqlite3")
    monkeypatch.setenv("EBAY_PROD_APP_ID", "prd-app")
    monkeypatch.setenv("EBAY_PROD_CERT_ID", "prd-cert")
    monkeypatch.setenv("EBAY_PROD_RUNAME", "prd-runame")
    monkeypatch.setenv("EBAY_ENV", "sandbox")
    client = TestClient(create_app())
    r = client.post("/api/ebay/target", json={"env": "live"})
    assert r.status_code == 200
    assert r.json()["env"] == "production"
    cfg.set_ebay_env_override(None)
    client2 = TestClient(create_app())
    assert client2.get("/api/health").json()["ebay"]["env"] == "production"


def test_sandbox_and_production_listings_stay_separate(tmp_path, monkeypatch):
    import dropship_desk.config as cfg
    from dropship_desk.db import get_candidate_by_asin, save_ebay_listing

    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cfg, "DB_PATH", tmp_path / "dropship.sqlite3")
    _seed_draft(tmp_path, monkeypatch)
    save_ebay_listing(
        "B0TESTASI1",
        {"status": "published", "env": "sandbox", "offer_id": "sbx", "listing_id": "1"},
    )
    cfg.set_ebay_env_override("production")
    save_ebay_listing(
        "B0TESTASI1",
        {"status": "unpublished", "env": "production", "offer_id": "prd", "listing_id": ""},
    )
    row = get_candidate_by_asin("B0TESTASI1")
    assert row is not None
    assert row["ebay_listing"]["offer_id"] == "prd"
    cfg.set_ebay_env_override("sandbox")
    row = get_candidate_by_asin("B0TESTASI1")
    assert row is not None
    assert row["ebay_listing"]["offer_id"] == "sbx"


def test_inventory_description_stays_under_4000():
    bullets = [f"Punkt {i} " + ("x" * 200) for i in range(20)]
    html = _inventory_description("Titel", bullets)
    assert 1 <= len(html) <= 4000
    assert "Titel" in html


def test_ebay_safe_description_strips_document_style_details_and_feedback():
    html = (
        "<!DOCTYPE html><html><head><style>.a{color:red}</style></head><body>"
        '<div class="dd-wrap"><h1>T</h1>'
        '<details class="x" open><summary>Versand</summary><div>3-7 Tage</div></details>'
        "<details><summary>Feedback</summary><p>positive Bewertung bitte</p></details>"
        "<p>Zahlung (z.&nbsp;B. PayPal, Karte)</p>"
        "<div class=\"dd-brand\">Dropship Desk Shop</div><p>zügig weitergeleitet. Abweichungen durch Lieferanten möglich.</p>"
        "<div>Dropship Desk Shop — Angebotstext</div></div></body></html>"
    )
    out = ebay_listing.ebay_safe_description(html)
    low = out.lower()
    for bad in ("<style", "doctype", "<html", "<head", "<details", "<summary", "class=", "bewertung", "paypal", "dropship", "weitergeleitet", "lieferant"):
        assert bad not in low, (bad, out)
    assert "<h3>Versand</h3>" in out and "3-7 Tage" in out and "<h1>T</h1>" in out


def test_prepare_image_makes_a_clean_neutral_copy(tmp_path):
    from PIL import Image

    from dropship_desk.ebay import pictures

    src = tmp_path / "01.jpg"
    exif = Image.Exif()
    exif[0x010E] = "amazon original"
    Image.new("RGB", (3000, 2000), (10, 120, 200)).save(src, format="JPEG", exif=exif)

    name, data = pictures.prepare_image(src)

    from io import BytesIO

    out = Image.open(BytesIO(data))
    assert name.startswith("img-") and name.endswith(".jpg") and "01" not in name
    assert max(out.size) == pictures.MAX_EDGE_PX
    assert not out.getexif()


def test_collect_image_urls_never_falls_back_to_amazon_links(monkeypatch):
    from dropship_desk.ebay import pictures

    monkeypatch.setattr(pictures, "upload_local_images", lambda asin: [])
    draft = {"media": {"source_urls": ["https://m.media-amazon.com/images/I/x.jpg"]}}
    with pytest.raises(RuntimeError, match="never sent"):
        pictures.collect_image_urls("B0TESTIMG1", draft)
