import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import sandbox_smoke as s  # noqa: E402


def fake_http(calls):
    def http(method, path, **kw):
        calls.append((method, path))
        if path.endswith("/publish"):
            return {"listingId": "110000000001"}
        if method == "POST" and path.endswith("/offer"):
            return {"offerId": "OFF1"}
        if method == "GET" and path.endswith("/offer"):
            return {"offers": []}
        if method == "GET" and "/offer/" in path:
            return {"status": "PUBLISHED"}
        return {}

    return http


def test_run_publishes_in_sandbox(monkeypatch):
    monkeypatch.setattr(s.account_setup, "ensure_seller_setup", lambda http: {
        "merchant_location_key": "k", "fulfillment_policy_id": "f", "payment_policy_id": "p", "return_policy_id": "r"})
    monkeypatch.setattr(s.taxonomy, "suggest_category", lambda t, http: {"category_id": "1", "tree_id": "77"})
    monkeypatch.setattr(s.taxonomy, "aspects_for_category", lambda c, t, http: {})
    calls = []
    out = s.run(publish=True, image_url="https://x/y.jpg", http=fake_http(calls))
    assert out["listing_id"] == "110000000001" and out["item_url"].startswith("https://www.sandbox.ebay.com/")
    assert ("POST", "/sell/inventory/v1/offer/OFF1/publish") in calls


def test_refuses_non_sandbox(monkeypatch):
    import pytest
    monkeypatch.setattr(s.config, "ebay_api_base", lambda: "https://api.ebay.com")
    with pytest.raises(SystemExit):
        s.force_sandbox()
