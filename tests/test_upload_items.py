"""Upload-items file pipeline: parser, production gate, sequential job, dedupe."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import dropship_desk.api as api_mod
import dropship_desk.upload_items as upload_items
from dropship_desk import config as cfg
from dropship_desk.ebay import listing as ebay_listing
from dropship_desk.models import EvaluateResponse, OfferIn


def _write_upload(tmp_path: Path, monkeypatch, text: str) -> Path:
    path = tmp_path / "upload_items.txt"
    path.write_text(text, encoding="utf-8")
    monkeypatch.setenv("UPLOAD_ITEMS_FILE", str(path))
    return path


def _offer(asin: str, total: float = 20.0) -> OfferIn:
    return OfferIn(
        title=f"Product {asin}",
        amazon_total=total,
        asin=asin,
        url=f"https://www.amazon.de/dp/{asin}",
        in_stock=True,
        seller_country="CN",
        sold_by_amazon=False,
        image_urls=[f"https://images.example/{asin}.jpg"],
    )


def _install_stubs(monkeypatch, *, missing=(), fetch_hook=None):
    calls: dict[str, list] = {
        "fetch": [],
        "evaluate": [],
        "draft": [],
        "stage": [],
        "publish": [],
    }

    def fake_fetch(asin: str) -> OfferIn:
        calls["fetch"].append(asin)
        if fetch_hook is not None:
            return fetch_hook(asin)
        if asin in missing:
            raise upload_items.AsinNotFound(
                f"ASIN_NOT_FOUND: {asin} — Amazon reports the product page does not exist"
            )
        return _offer(asin)

    def fake_evaluate(body, *, persist=None):
        calls["evaluate"].append((body.asin_or_url, persist))
        offer = body.offer
        return EvaluateResponse(
            asin=offer.asin,
            offer=offer,
            ebay_price=50.0,
            max_amazon_buy=offer.amazon_total,
            suggested_ebay_price=50.0,
            passed=True,
            hard_reject_reasons=[],
            margin={"passed": True, "fail_reasons": []},
            candidate_id=1,
            status="ready",
        )

    def fake_draft(
        asin,
        ebay_price=None,
        amazon_total=None,
        title=None,
        force_refresh_images=False,
        *,
        offer=None,
        evaluate=True,
    ):
        calls["draft"].append(asin)
        return {
            "asin": asin,
            "draft": {
                "title": f"eBay title {asin}",
                "description_html": "<p>copy</p>",
                "bullet_points": ["one"],
            },
            "media": {},
            "artifacts": {},
        }

    def fake_stage(asin):
        calls["stage"].append(asin)
        ebay_listing.save_listing_state(
            asin,
            {"status": "unpublished", "offer_id": f"OFF-{asin}", "listing_id": ""},
        )
        return ebay_listing.public_listing(asin)

    def fake_publish(asin):
        calls["publish"].append(asin)
        state = ebay_listing.load_listing_state(asin)
        ebay_listing.save_listing_state(
            asin,
            {
                **state,
                "status": "published",
                "listing_id": f"1100{asin}",
                "offer_id": state.get("offer_id") or f"OFF-{asin}",
            },
        )
        return ebay_listing.public_listing(asin)

    monkeypatch.setattr(upload_items, "fetch_product_offer", fake_fetch)
    monkeypatch.setattr(upload_items, "run_evaluate", fake_evaluate)
    monkeypatch.setattr(upload_items, "generate_draft", fake_draft)
    monkeypatch.setattr(upload_items.ebay_listing, "stage_unpublished", fake_stage)
    monkeypatch.setattr(upload_items.ebay_listing, "publish_offer", fake_publish)
    return calls


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cfg, "DB_PATH", tmp_path / "dropship.sqlite3")
    monkeypatch.setattr(cfg, "ebay_env", lambda: "sandbox")
    monkeypatch.setattr(upload_items.ebay_oauth, "oauth_connected", lambda env=None: True)
    monkeypatch.setattr(api_mod, "UPLOAD_JOB", upload_items.UploadJobManager())
    return TestClient(api_mod.create_app())


def _wait_done(client: TestClient, timeout: float = 10.0) -> dict:
    deadline = time.time() + timeout
    last: dict = {}
    while time.time() < deadline:
        last = client.get("/api/upload-items/status").json()
        if not last.get("running"):
            return last
        time.sleep(0.01)
    raise AssertionError(f"upload job did not finish: {last}")


def test_parser_aliases_junk_comments_and_duplicates(tmp_path):
    path = tmp_path / "upload_items.txt"
    path.write_text(
        "\n".join(
            [
                "# a comment",
                "",
                "https://www.amazon.de/dp/B0AAA11111?tag=abc",
                "https://amazon.de/gp/product/B0BBB22222",
                "B0CCC33333",
                "not a link",
                "https://www.amazon.de/dp/B0AAA11111",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    rows = upload_items.read_upload_file(path)

    assert [(r.asin, r.state) for r in rows[:3]] == [
        ("B0AAA11111", "queued"),
        ("B0BBB22222", "queued"),
        ("B0CCC33333", "queued"),
    ]
    rejected = next(r for r in rows if r.state == "rejected")
    assert rejected.reason == "no_asin"
    duplicate = next(r for r in rows if r.state == "duplicate_in_file")
    assert duplicate.asin == "B0AAA11111"
    assert "duplicate" in duplicate.reason.lower()
    assert len(rows) == 5


def test_missing_file_preview_is_clear_404(client, tmp_path, monkeypatch):
    missing = tmp_path / "nope" / "upload_items.txt"
    monkeypatch.setenv("UPLOAD_ITEMS_FILE", str(missing))

    r = client.get("/api/upload-items/preview")

    assert r.status_code == 404
    detail = r.json()["detail"]
    assert "UPLOAD_FILE_MISSING" in detail
    assert str(missing) in detail


def test_production_refuses_before_any_work(client, tmp_path, monkeypatch):
    calls = _install_stubs(monkeypatch)
    _write_upload(
        tmp_path,
        monkeypatch,
        "https://www.amazon.de/dp/B0PROD0001\nhttps://www.amazon.de/dp/B0PROD0002\n",
    )
    monkeypatch.setattr(cfg, "ebay_env", lambda: "production")

    r = client.post("/api/upload-items/start")

    assert r.status_code == 403
    body = r.json()
    assert body["code"] == "LIVE_UPLOAD_DISABLED"
    assert r.headers.get("content-type", "").startswith("application/json")
    for name, seen in calls.items():
        assert seen == [], f"{name} was called in production: {seen}"
    status = client.get("/api/upload-items/status").json()
    assert status["running"] is False


def test_sandbox_happy_path_publishes_two_asins(client, tmp_path, monkeypatch):
    calls = _install_stubs(monkeypatch)
    _write_upload(
        tmp_path,
        monkeypatch,
        "https://www.amazon.de/dp/B0HAPPY001\nhttps://www.amazon.de/dp/B0HAPPY002\n",
    )

    r = client.post("/api/upload-items/start")
    assert r.status_code == 200
    status = _wait_done(client)

    assert status["target_env"] == "sandbox"
    assert [row["state"] for row in status["rows"]] == ["published", "published"]
    assert calls["fetch"] == ["B0HAPPY001", "B0HAPPY002"]
    assert calls["stage"] == ["B0HAPPY001", "B0HAPPY002"]
    assert calls["publish"] == ["B0HAPPY001", "B0HAPPY002"]
    assert status["counters"]["published"] == 2
    assert all(row["item_url"].startswith("https://www.sandbox.ebay.com/itm/") for row in status["rows"])


def test_asin_not_found_is_skipped_and_run_continues(client, tmp_path, monkeypatch):
    calls = _install_stubs(monkeypatch, missing={"B0MISS0001"})
    _write_upload(
        tmp_path,
        monkeypatch,
        "https://www.amazon.de/dp/B0MISS0001\nhttps://www.amazon.de/dp/B0AFTER001\n",
    )

    client.post("/api/upload-items/start")
    status = _wait_done(client)

    assert [row["state"] for row in status["rows"]] == ["not_found", "published"]
    assert "ASIN_NOT_FOUND" in status["rows"][0]["reason"]
    assert calls["publish"] == ["B0AFTER001"]
    assert status["phase"] == "finished"


def test_second_start_while_running_is_409_with_run_id(client, tmp_path, monkeypatch):
    started = threading.Event()
    release = threading.Event()

    def blocking_fetch(asin: str) -> OfferIn:
        started.set()
        assert release.wait(timeout=10)
        return _offer(asin)

    _install_stubs(monkeypatch, fetch_hook=blocking_fetch)
    _write_upload(tmp_path, monkeypatch, "https://www.amazon.de/dp/B0BLOCK001\n")

    try:
        assert client.post("/api/upload-items/start").status_code == 200
        assert started.wait(timeout=5)
        current = client.get("/api/upload-items/status").json()

        r = client.post("/api/upload-items/start")

        assert r.status_code == 409
        assert current["run_id"] in r.json()["detail"]
    finally:
        release.set()
    status = _wait_done(client)
    assert status["rows"][0]["state"] == "published"


def test_second_run_after_completion_skips_published_rows(client, tmp_path, monkeypatch):
    calls = _install_stubs(monkeypatch)
    _write_upload(tmp_path, monkeypatch, "https://www.amazon.de/dp/B0ONCE0001\n")

    client.post("/api/upload-items/start")
    first = _wait_done(client)
    assert first["rows"][0]["state"] == "published"
    stage_calls = len(calls["stage"])
    publish_calls = len(calls["publish"])

    client.post("/api/upload-items/start")
    second = _wait_done(client)

    assert second["rows"][0]["state"] == "skipped_existing"
    assert len(calls["stage"]) == stage_calls
    assert len(calls["publish"]) == publish_calls


def test_chrome_not_found_aborts_the_run(client, tmp_path, monkeypatch):
    def broken_fetch(asin: str) -> OfferIn:
        raise upload_items.ChromeNotFound("CHROME_NOT_FOUND: cannot launch installed Chrome")

    calls = _install_stubs(monkeypatch, fetch_hook=broken_fetch)
    _write_upload(
        tmp_path,
        monkeypatch,
        "https://www.amazon.de/dp/B0CHROME01\nhttps://www.amazon.de/dp/B0CHROME02\n",
    )

    client.post("/api/upload-items/start")
    status = _wait_done(client)

    assert status["running"] is False
    assert status["phase"] == "aborted"
    assert "CHROME_NOT_FOUND" in status["error"]
    assert status["rows"][0]["state"] == "error"
    assert status["rows"][1]["state"] == "queued"
    assert calls["stage"] == []
    assert calls["publish"] == []


def test_target_change_during_run_aborts_before_stage(client, tmp_path, monkeypatch):
    holder = {"env": "sandbox"}
    monkeypatch.setattr(cfg, "ebay_env", lambda: holder["env"])

    def flipping_fetch(asin: str) -> OfferIn:
        holder["env"] = "production"
        return _offer(asin)

    calls = _install_stubs(monkeypatch, fetch_hook=flipping_fetch)
    _write_upload(tmp_path, monkeypatch, "https://www.amazon.de/dp/B0TARGET01\n")

    client.post("/api/upload-items/start")
    status = _wait_done(client)

    assert status["running"] is False
    assert status["phase"] == "aborted_target_changed"
    assert calls["stage"] == []
    assert calls["publish"] == []
