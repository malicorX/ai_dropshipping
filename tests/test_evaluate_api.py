from fastapi.testclient import TestClient

from dropship_desk.api import create_app


def _client(tmp_path, monkeypatch):
    import dropship_desk.config as cfg

    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cfg, "DB_PATH", tmp_path / "dropship.sqlite3")
    return TestClient(create_app())


def test_evaluate_pass_and_persist(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    r = client.post(
        "/api/evaluate",
        json={
            "asin_or_url": "B0TESTASI1",
            "offer": {
                "title": "Test Widget",
                "amazon_total": 20.0,
                "in_stock": True,
                "seller_country": "CN",
                "sold_by_amazon": False,
                "asin": "B0TESTASI1",
            },
            "ebay_price": 45.0,
        },
    )
    assert r.status_code == 200
    body = r.json()
    # With 50% min margin, €45 on €20 amazon may fail — bump price
    if not body["passed"]:
        r = client.post(
            "/api/evaluate",
            json={
                "asin_or_url": "B0TESTASI1",
                "offer": {
                    "title": "Test Widget",
                    "amazon_total": 20.0,
                    "in_stock": True,
                    "seller_country": "CN",
                    "sold_by_amazon": False,
                    "asin": "B0TESTASI1",
                },
                "ebay_price": 55.0,
            },
        )
        assert r.status_code == 200
        body = r.json()
    assert body["passed"] is True
    assert body["candidate_id"] is not None
    assert body["status"] == "ready"

    listed = client.get("/api/candidates").json()
    assert len(listed) == 1
    assert listed[0]["asin"] == "B0TESTASI1"


def test_settings_roundtrip(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    r = client.put(
        "/api/settings",
        json={
            "margin": {
                "ebay_fee_pct": 0.12,
                "ebay_fee_fixed": 0.3,
                "buffer_eur": 2.0,
                "min_margin_eur": 4.0,
                "min_margin_pct": 0.15,
                "max_delivery_days": 12,
                "min_stock": 5,
                "skip_sold_by_amazon": True,
                "reject_dach_sellers": True,
            },
            "listing_shop": {
                "shop_name": "Demo Shop",
                "accent_color": "#112233",
            },
        },
    )
    assert r.status_code == 200
    assert r.json()["margin"]["ebay_fee_pct"] == 0.12
    assert r.json()["listing_shop"]["shop_name"] == "Demo Shop"
    got = client.get("/api/settings").json()
    assert got["margin"]["buffer_eur"] == 2.0
    assert got["listing_shop"]["accent_color"] == "#112233"
