"""Prepare mode (no eBay writes), prepared overview and publish-selected.

All tests are local-only: Amazon fetch, the LLM draft, evaluate, stage and
publish are replaced by spies/stubs.  No network and no real LLM is used.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import dropship_desk.api as api_mod
import dropship_desk.prepared as prepared_mod
import dropship_desk.upload_items as upload_items
from dropship_desk import config as cfg
from dropship_desk import db
from dropship_desk.ebay import listing as ebay_listing
from dropship_desk.models import EvaluateResponse, OfferIn


def _write_upload(tmp_path: Path, monkeypatch, text: str) -> Path:
    path = tmp_path / "upload_items.txt"
    path.write_text(text, encoding="utf-8")
    monkeypatch.setenv("UPLOAD_ITEMS_FILE", str(path))
    return path


_DEFAULT_RETRY_PASSES = upload_items.MAX_RETRY_PASSES


@pytest.fixture(autouse=True)
def _retry_passes_enabled(monkeypatch):
    """Retries are off by default; these tests exercise the mechanism itself."""
    monkeypatch.setattr(upload_items, "MAX_RETRY_PASSES", 2)


def _offer(asin: str, total: float = 20.0, label: str = "") -> OfferIn:
    return OfferIn(
        title=f"Product {asin}",
        amazon_total=total,
        asin=asin,
        url=f"https://www.amazon.de/dp/{asin}",
        in_stock=True,
        seller_country="CN",
        sold_by_amazon=False,
        image_urls=[f"https://images.example/{asin}.jpg"],
        variation_label=label,
    )


def _seed_prepared(asin: str, *, draft_title: str | None = None) -> None:
    db.upsert_candidate(
        asin=asin,
        title=f"Amazon {asin}",
        amazon_total=20.0,
        ebay_price=50.0,
        max_amazon_buy=20.0,
        status="ready",
        offer={"title": f"Amazon {asin}"},
        margin={"passed": True, "fail_reasons": [], "margin_pct": 0.55},
        hard_reject=[],
    )
    # A passed empty string means "candidate without a draft".
    if draft_title != "":
        db.save_listing_draft(
            asin,
            {
                "title": draft_title or f"eBay title {asin}",
                "description_html": "<p>copy</p>",
                "bullet_points": ["one"],
            },
        )


def _install_stubs(
    monkeypatch,
    *,
    draft_title: str | None = "eBay title",
    evaluation_passed: bool = True,
    fail_reasons: list[str] | None = None,
    stage_raises: bool = False,
):
    calls: dict[str, list] = {
        "fetch": [],
        "evaluate": [],
        "draft": [],
        "stage": [],
        "publish": [],
        "order": [],
        "oauth": [],
    }

    def fake_fetch(asin: str) -> OfferIn:
        calls["fetch"].append(asin)
        return _offer(asin)

    def fake_evaluate(body, *, persist=None):
        calls["evaluate"].append((body.asin_or_url, persist))
        offer = body.offer
        margin = {
            "passed": evaluation_passed,
            "fail_reasons": list(fail_reasons or []),
        }
        # Mirror the real run_evaluate(save=True): the candidate row is saved.
        db.upsert_candidate(
            asin=offer.asin,
            title=offer.title,
            amazon_total=offer.amazon_total,
            ebay_price=50.0,
            max_amazon_buy=offer.amazon_total,
            status="ready" if evaluation_passed else "rejected",
            offer=offer.model_dump(),
            margin=margin,
            hard_reject=[],
        )
        return EvaluateResponse(
            asin=offer.asin,
            offer=offer,
            ebay_price=50.0,
            max_amazon_buy=offer.amazon_total,
            suggested_ebay_price=50.0,
            passed=evaluation_passed,
            hard_reject_reasons=[],
            margin=margin,
            candidate_id=1,
            status="ready" if evaluation_passed else "rejected",
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
                "title": draft_title if draft_title is not None else "",
                "description_html": "<p>copy</p>",
                "bullet_points": ["one"],
            },
            "media": {},
            "artifacts": {},
        }

    def fake_stage(asin, draft_patch=None):
        calls["stage"].append(asin)
        calls["order"].append("stage")
        if stage_raises:
            raise AssertionError("stage_unpublished must not be called")
        ebay_listing.save_listing_state(
            asin,
            {"status": "unpublished", "offer_id": f"OFF-{asin}", "listing_id": ""},
        )
        return ebay_listing.public_listing(asin)

    def fake_publish(asin):
        calls["publish"].append(asin)
        calls["order"].append("publish")
        if stage_raises:
            raise AssertionError("publish_offer must not be called")
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

    def fake_offers(fetched: str) -> list[OfferIn]:
        return [fake_fetch(fetched)]

    monkeypatch.setattr(upload_items, "fetch_variation_offers", fake_offers)
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


# --------------------------------------------------------------- prepare mode


def test_prepare_mode_makes_zero_ebay_calls_and_ends_prepared(
    client, tmp_path, monkeypatch
):
    calls = _install_stubs(monkeypatch, stage_raises=True)
    # Prepare mode must not even ask for OAuth sign-in.
    monkeypatch.setattr(
        upload_items.ebay_oauth,
        "oauth_connected",
        lambda env=None: (_ for _ in ()).throw(
            AssertionError("oauth_connected must not be called in prepare mode")
        ),
    )
    _write_upload(tmp_path, monkeypatch, "https://www.amazon.de/dp/B0PREP0001\n")

    r = client.post("/api/upload-items/start", json={"mode": "prepare"})
    assert r.status_code == 200
    status = _wait_done(client)

    assert status["mode"] == "prepare"
    assert [row["state"] for row in status["rows"]] == ["prepared"], status["rows"][0]["reason"]
    assert status["rows"][0]["started_at"]
    assert status["rows"][0]["finished_at"]
    assert status["rows"][0]["duration_sec"] is not None
    assert status["counters"]["prepared"] == 1
    assert status["counters"]["published"] == 0
    assert calls["fetch"] == ["B0PREP0001"]
    assert calls["evaluate"] == [("B0PREP0001", "always")]
    assert calls["draft"] == ["B0PREP0001"]
    # The spies raise, so any eBay call would turn the row into an error.
    assert calls["stage"] == []
    assert calls["publish"] == []
    assert cfg.upload_sandbox_pinned() is False


def test_prepare_mode_persists_title_patch_into_stored_draft(
    client, tmp_path, monkeypatch
):
    asin = "B0PREP0002"

    def child_offers(_asin: str) -> list[OfferIn]:
        return [_offer(asin, label="Red / G2")]

    calls = _install_stubs(monkeypatch, draft_title=f"eBay title {asin}")
    # Patch after the shared stubs so the variation page wins.
    monkeypatch.setattr(upload_items, "fetch_variation_offers", child_offers)
    _write_upload(tmp_path, monkeypatch, f"https://www.amazon.de/dp/{asin}\n")

    client.post("/api/upload-items/start", json={"mode": "prepare"})
    status = _wait_done(client)

    assert status["rows"][0]["state"] == "prepared"
    assert calls["draft"] == [asin]
    stored = db.get_listing_draft(asin)
    assert stored is not None
    assert stored["title"] == f"eBay title {asin} - Red / G2"


def test_second_prepare_skips_without_fetch_or_llm(client, tmp_path, monkeypatch):
    calls = _install_stubs(monkeypatch)
    _write_upload(tmp_path, monkeypatch, "https://www.amazon.de/dp/B0PREP0003\n")

    client.post("/api/upload-items/start", json={"mode": "prepare"})
    first = _wait_done(client)
    assert first["rows"][0]["state"] == "prepared"
    fetch_calls = len(calls["fetch"])
    draft_calls = len(calls["draft"])
    evaluate_calls = len(calls["evaluate"])

    r = client.post("/api/upload-items/start", json={"mode": "prepare"})
    assert r.status_code == 200
    second = _wait_done(client)

    row = second["rows"][0]
    assert row["state"] == "skipped_existing"
    assert row["reason"] == "haben wir schon (vorbereitet)"
    assert len(calls["fetch"]) == fetch_calls
    assert len(calls["draft"]) == draft_calls
    assert len(calls["evaluate"]) == evaluate_calls


def test_prepare_of_already_published_row_is_skipped_before_fetch(
    client, tmp_path, monkeypatch
):
    asin = "B0PREP0004"
    calls = _install_stubs(monkeypatch)
    ebay_listing.save_listing_state(
        asin,
        {
            "status": "published",
            "offer_id": f"OFF-{asin}",
            "listing_id": f"1100{asin}",
        },
    )
    _write_upload(tmp_path, monkeypatch, f"https://www.amazon.de/dp/{asin}\n")

    client.post("/api/upload-items/start", json={"mode": "prepare"})
    status = _wait_done(client)

    assert status["rows"][0]["state"] == "skipped_existing"
    assert status["rows"][0]["reason"] == "haben wir schon"
    assert calls["fetch"] == []
    assert calls["draft"] == []


def test_unknown_start_mode_is_400(client, tmp_path, monkeypatch):
    _install_stubs(monkeypatch)
    _write_upload(tmp_path, monkeypatch, "https://www.amazon.de/dp/B0PREP0005\n")

    r = client.post("/api/upload-items/start", json={"mode": "turbo"})

    assert r.status_code == 400


# ------------------------------------------------------------------- overview


def test_list_prepared_excludes_published_and_includes_unpublished_offers(
    client, monkeypatch
):
    _seed_prepared("B0OVRV0001")  # never sent to eBay -> none
    _seed_prepared("B0OVRV0002")  # staged offer -> unpublished
    _seed_prepared("B0OVRV0003")  # published -> excluded
    _seed_prepared("B0OVRV0004", draft_title="")  # no draft -> excluded
    ebay_listing.save_listing_state(
        "B0OVRV0002",
        {"status": "unpublished", "offer_id": "OFF-2", "listing_id": ""},
    )
    ebay_listing.save_listing_state(
        "B0OVRV0003",
        {
            "status": "published",
            "offer_id": "OFF-3",
            "listing_id": "1100B0OVRV0003",
        },
    )

    r = client.get("/api/prepared")

    assert r.status_code == 200
    body = r.json()
    assert body["target_env"] == "sandbox"
    assert body["live_disabled"] is False
    by_asin = {item["asin"]: item for item in body["items"]}
    assert set(by_asin) == {"B0OVRV0001", "B0OVRV0002"}
    none_item = by_asin["B0OVRV0001"]
    assert none_item["ebay_status"] == "none"
    assert none_item["offer_id"] == ""
    assert none_item["title"].startswith("eBay title")
    assert none_item["ebay_price"] == 50.0
    assert none_item["amazon_total"] == 20.0
    assert none_item["margin"]["margin_pct"] == 0.55
    assert none_item["prepared_at"]
    assert none_item["age_days"] >= 0
    staged = by_asin["B0OVRV0002"]
    assert staged["ebay_status"] == "unpublished"
    assert staged["offer_id"] == "OFF-2"


def test_list_prepared_is_read_only_and_local(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cfg, "DB_PATH", tmp_path / "dropship.sqlite3")
    _seed_prepared("B0OVRV0005")

    def boom(*_args, **_kwargs):
        raise AssertionError("list_prepared must not touch the network")

    monkeypatch.setattr(upload_items, "fetch_variation_offers", boom)
    monkeypatch.setattr(upload_items.ebay_listing, "stage_unpublished", boom)
    monkeypatch.setattr(upload_items.ebay_listing, "publish_offer", boom)

    items = prepared_mod.list_prepared()

    assert [item["asin"] for item in items] == ["B0OVRV0005"], items


def test_prepared_overview_marks_production_as_live_disabled(client, monkeypatch):
    _seed_prepared("B0OVRV0006")
    monkeypatch.setattr(cfg, "ebay_env", lambda: "production")

    body = client.get("/api/prepared").json()

    assert body["target_env"] == "production"
    assert body["live_disabled"] is True


# ------------------------------------------------------------ publish selected


def test_publish_rechecks_price_and_rejects_without_staging(
    client, monkeypatch
):
    asin = "B0PUB00001"
    _seed_prepared(asin)
    calls = _install_stubs(
        monkeypatch,
        evaluation_passed=False,
        fail_reasons=["margin below minimum"],
        stage_raises=True,
    )

    r = client.post("/api/prepared/publish", json={"asins": [asin]})

    assert r.status_code == 200
    status = _wait_done(client)
    row = status["rows"][0]
    assert status["mode"] == "publish"
    assert row["state"] == "rejected"
    assert "margin below minimum" in row["reason"]
    assert calls["evaluate"] == [(asin, "always")]
    # No draft regeneration and no eBay write after a failed margin gate.
    assert calls["draft"] == []
    assert calls["stage"] == []
    assert calls["publish"] == []


def test_publish_happy_path_stages_then_publishes_once(client, monkeypatch):
    asin = "B0PUB00002"
    _seed_prepared(asin)
    calls = _install_stubs(monkeypatch)

    r = client.post("/api/prepared/publish", json={"asins": [asin]})

    assert r.status_code == 200
    status = _wait_done(client)
    row = status["rows"][0]
    assert status["mode"] == "publish"
    assert row["state"] == "published"
    assert calls["fetch"] == [asin]
    assert calls["evaluate"] == [(asin, "always")]
    assert calls["order"] == ["stage", "publish"]
    assert row["offer_id"] == f"OFF-{asin}"
    assert row["listing_id"] == f"1100{asin}"
    assert status["counters"]["published"] == 1


def test_publish_reports_unknown_and_published_without_error(
    client, monkeypatch
):
    published = "B0PUB00003"
    _seed_prepared(published)
    ebay_listing.save_listing_state(
        published,
        {
            "status": "published",
            "offer_id": f"OFF-{published}",
            "listing_id": f"1100{published}",
        },
    )
    calls = _install_stubs(monkeypatch)

    r = client.post(
        "/api/prepared/publish",
        json={"asins": ["B0UNKNOWN1", published]},
    )

    assert r.status_code == 200
    status = _wait_done(client)
    states = {row["asin"]: row["state"] for row in status["rows"]}
    assert states["B0UNKNOWN1"] == "not_prepared"
    assert states[published] == "skipped_existing"
    assert calls["fetch"] == []
    assert calls["stage"] == []
    assert calls["publish"] == []


@pytest.mark.parametrize("body", [{}, {"asins": []}, {"asins": None}])
def test_publish_empty_list_is_400(client, monkeypatch, body):
    _install_stubs(monkeypatch)

    r = client.post("/api/prepared/publish", json=body)

    assert r.status_code == 400


def test_publish_without_body_is_400(client, monkeypatch):
    _install_stubs(monkeypatch)

    r = client.post("/api/prepared/publish")

    assert r.status_code == 400


def test_production_refuses_prepare_and_publish(client, tmp_path, monkeypatch):
    calls = _install_stubs(monkeypatch)
    _seed_prepared("B0PROD0009")
    _write_upload(tmp_path, monkeypatch, "https://www.amazon.de/dp/B0PROD0009\n")
    monkeypatch.setattr(cfg, "ebay_env", lambda: "production")

    prepare = client.post("/api/upload-items/start", json={"mode": "prepare"})
    publish = client.post(
        "/api/prepared/publish", json={"asins": ["B0PROD0009"]}
    )

    assert prepare.status_code == 403
    assert prepare.json()["code"] == "LIVE_UPLOAD_DISABLED"
    assert publish.status_code == 403
    assert publish.json()["code"] == "LIVE_UPLOAD_DISABLED"
    assert client.get("/api/upload-items/status").json()["running"] is False
    for name, seen in calls.items():
        assert seen == [], f"{name} was called in production: {seen}"


def test_publish_requires_sign_in(client, monkeypatch):
    _seed_prepared("B0PUB00004")
    calls = _install_stubs(monkeypatch)
    monkeypatch.setattr(
        upload_items.ebay_oauth, "oauth_connected", lambda env=None: False
    )

    r = client.post("/api/prepared/publish", json={"asins": ["B0PUB00004"]})

    assert r.status_code == 409
    assert "NOT_SIGNED_IN" in r.json()["detail"]
    assert calls["stage"] == []
    assert calls["publish"] == []


def test_publish_reuses_single_flight_lock(client, monkeypatch):
    import threading

    started = threading.Event()
    release = threading.Event()
    _seed_prepared("B0PUB00005")

    def blocking_stage(asin, draft_patch=None):
        started.set()
        assert release.wait(timeout=10)
        return ebay_listing.public_listing(asin)

    calls = _install_stubs(monkeypatch)
    monkeypatch.setattr(upload_items.ebay_listing, "stage_unpublished", blocking_stage)

    try:
        assert (
            client.post(
                "/api/prepared/publish", json={"asins": ["B0PUB00005"]}
            ).status_code
            == 200
        )
        assert started.wait(timeout=5)
        again = client.post(
            "/api/prepared/publish", json={"asins": ["B0PUB00005"]}
        )
        assert again.status_code == 409
        assert calls["publish"] == []
    finally:
        release.set()
    status = _wait_done(client)
    assert status["rows"][0]["state"] == "published"


# ------------------------------------------------- hardening: ASIN validation


def _data_listing(path: Path) -> list[str]:
    return sorted(entry.name for entry in path.iterdir())


@pytest.mark.parametrize("bad", ["../../ESCB3B6D7", "../../B0VALID001", {"a": 1}, None, "not-an-asin", 12345, 1234567890])
def test_publish_all_invalid_asins_is_400_and_creates_nothing(
    client, tmp_path, monkeypatch, bad
):
    calls = _install_stubs(monkeypatch)
    before = _data_listing(tmp_path)

    r = client.post("/api/prepared/publish", json={"asins": [bad]})

    assert r.status_code == 400
    assert _data_listing(tmp_path) == before
    assert not (tmp_path / "products").exists()
    for name, seen in calls.items():
        assert seen == [], f"{name} was called for an invalid ASIN: {seen}"
    assert client.get("/api/upload-items/status").json()["running"] is False


def test_publish_invalid_asin_becomes_not_prepared_and_never_touches_disk(
    client, tmp_path, monkeypatch
):
    valid = "B0VALID001"
    _seed_prepared(valid)
    calls = _install_stubs(monkeypatch)
    before = _data_listing(tmp_path)

    r = client.post(
        "/api/prepared/publish",
        json={"asins": ["../../ESCB3B6D7", {"a": 1}, None, valid]},
    )

    assert r.status_code == 200
    status = _wait_done(client)
    invalid_rows = [row for row in status["rows"] if row["asin"] != valid]
    assert len(invalid_rows) == 3
    for row in invalid_rows:
        assert row["state"] == "not_prepared"
        assert row["reason"] == "invalid asin"
        assert row["asin"] == ""
    states = {row["asin"]: row["state"] for row in status["rows"] if row["asin"]}
    assert states == {valid: "published"}
    assert calls["fetch"] == [valid]
    # The only new directory is the legitimate product dir for the valid ASIN.
    after = set(_data_listing(tmp_path))
    assert after - set(before) == {"products"}
    assert sorted(p.name for p in (tmp_path / "products").iterdir()) == [valid]


# --------------------------------------- hardening: publish uses prepared price


def _install_real_evaluate_with_ebay_spies(monkeypatch, *, total: float):
    """Real run_evaluate; only the Amazon fetch and eBay writes are stubbed."""
    calls: dict[str, list[str]] = {
        "fetch": [],
        "stage": [],
        "publish": [],
        "order": [],
    }

    def fake_offers(asin: str) -> list[OfferIn]:
        calls["fetch"].append(asin)
        return [_offer(asin, total=total)]

    def fake_stage(asin, draft_patch=None):
        calls["stage"].append(asin)
        calls["order"].append("stage")
        ebay_listing.save_listing_state(
            asin,
            {"status": "unpublished", "offer_id": f"OFF-{asin}", "listing_id": ""},
        )
        return ebay_listing.public_listing(asin)

    def fake_publish(asin):
        calls["publish"].append(asin)
        calls["order"].append("publish")
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

    monkeypatch.setattr(upload_items, "fetch_variation_offers", fake_offers)
    monkeypatch.setattr(upload_items.ebay_listing, "stage_unpublished", fake_stage)
    monkeypatch.setattr(upload_items.ebay_listing, "publish_offer", fake_publish)
    return calls


def test_publish_rejects_when_amazon_price_rose_against_prepared_price(
    client, monkeypatch
):
    asin = "B0PRICE001"
    _seed_prepared(asin)  # stored amazon 20 / prepared eBay price 50
    calls = _install_real_evaluate_with_ebay_spies(monkeypatch, total=45.0)

    r = client.post("/api/prepared/publish", json={"asins": [asin]})

    assert r.status_code == 200
    status = _wait_done(client)
    row = status["rows"][0]
    assert row["state"] == "rejected"
    assert "price changed" in row["reason"]
    assert "prepared 50.00 EUR" in row["reason"]
    assert "Amazon now 45.00" in row["reason"]
    assert calls["stage"] == []
    assert calls["publish"] == []
    assert calls["order"] == []
    stored = db.get_candidate_by_asin(asin)
    assert stored is not None
    assert stored["ebay_price"] == 50.0


def test_publish_still_fine_price_publishes_at_prepared_price(client, monkeypatch):
    asin = "B0PRICE002"
    _seed_prepared(asin)  # stored amazon 20 / prepared eBay price 50
    calls = _install_real_evaluate_with_ebay_spies(monkeypatch, total=20.0)

    r = client.post("/api/prepared/publish", json={"asins": [asin]})

    assert r.status_code == 200
    status = _wait_done(client)
    assert status["rows"][0]["state"] == "published"
    assert calls["order"] == ["stage", "publish"]
    stored = db.get_candidate_by_asin(asin)
    assert stored is not None
    # Never replaced by the lower suggested price.
    assert stored["ebay_price"] == 50.0


# ------------------------------------------------------ mutant-killing tests


def test_publish_skips_when_listing_appears_during_evaluate(
    client, monkeypatch
):
    """M1: the post-evaluate already-published check is required."""
    asin = "B0RACE0001"
    _seed_prepared(asin)
    calls = _install_stubs(monkeypatch)

    def publish_during_fetch(fetched: str) -> list[OfferIn]:
        calls["fetch"].append(fetched)
        ebay_listing.save_listing_state(
            asin,
            {
                "status": "published",
                "offer_id": f"OFF-{asin}",
                "listing_id": f"1100{asin}",
            },
        )
        return [_offer(fetched)]

    monkeypatch.setattr(upload_items, "fetch_variation_offers", publish_during_fetch)

    client.post("/api/prepared/publish", json={"asins": [asin]})
    status = _wait_done(client)

    assert status["rows"][0]["state"] == "skipped_existing"
    assert calls["stage"] == []
    assert calls["publish"] == []


def test_publish_target_flip_after_stage_aborts_before_publish(
    client, monkeypatch
):
    """M2: the _check_target() immediately before publish_offer is required."""
    asin = "B0FLIPP001"
    _seed_prepared(asin)
    holder = {"env": "sandbox"}
    monkeypatch.setattr(cfg, "ebay_env", lambda: holder["env"])
    calls = _install_stubs(monkeypatch)

    def flipping_stage(fetched, draft_patch=None):
        calls["stage"].append(fetched)
        calls["order"].append("stage")
        ebay_listing.save_listing_state(
            fetched,
            {"status": "unpublished", "offer_id": f"OFF-{fetched}", "listing_id": ""},
        )
        holder["env"] = "production"
        return ebay_listing.public_listing(fetched)

    monkeypatch.setattr(upload_items.ebay_listing, "stage_unpublished", flipping_stage)

    client.post("/api/prepared/publish", json={"asins": [asin]})
    status = _wait_done(client)

    assert status["phase"] == "aborted_target_changed"
    assert calls["publish"] == []
    assert status["rows"][0]["state"] == "error"


def test_publish_rejects_variation_parent_without_evaluate_or_write(
    client, monkeypatch
):
    """M3: the publish path must keep the variation-parent rejection."""
    parent = "B0PARENT02"
    _seed_prepared(parent)
    calls = _install_stubs(monkeypatch)

    def parent_offers(asin: str) -> list[OfferIn]:
        return [_offer("B0CHILD001"), _offer("B0CHILD002")]

    monkeypatch.setattr(upload_items, "fetch_variation_offers", parent_offers)

    client.post("/api/prepared/publish", json={"asins": [parent]})
    status = _wait_done(client)

    row = status["rows"][0]
    assert row["state"] == "rejected"
    assert row["reason"] == "variation_parent"
    assert calls["evaluate"] == []
    assert calls["stage"] == []
    assert calls["publish"] == []


def test_publish_stop_after_first_row_leaves_second_queued(
    client, monkeypatch
):
    """M7: a stop request must end the batch between rows."""
    import threading

    first, second = "B0STOP0001", "B0STOP0002"
    _seed_prepared(first)
    _seed_prepared(second)
    started = threading.Event()
    release = threading.Event()
    calls = _install_stubs(monkeypatch)

    def blocking_stage(asin, draft_patch=None):
        calls["stage"].append(asin)
        calls["order"].append("stage")
        if asin == first:
            started.set()
            assert release.wait(timeout=10)
        ebay_listing.save_listing_state(
            asin,
            {"status": "unpublished", "offer_id": f"OFF-{asin}", "listing_id": ""},
        )
        return ebay_listing.public_listing(asin)

    monkeypatch.setattr(upload_items.ebay_listing, "stage_unpublished", blocking_stage)

    try:
        r = client.post("/api/prepared/publish", json={"asins": [first, second]})
        assert r.status_code == 200
        assert started.wait(timeout=5)
        stopped = client.post("/api/upload-items/stop", json={})
        assert stopped.status_code == 200
        assert stopped.json()["stop_requested"] is True
    finally:
        release.set()

    status = _wait_done(client)
    rows = {row["asin"]: row["state"] for row in status["rows"]}
    assert status["phase"] == "stopped"
    assert rows[first] == "published"
    assert rows[second] == "queued"
    assert calls["stage"] == [first]


def test_list_prepared_ignores_listing_state_from_another_env(client, monkeypatch):
    """M4: the stored env guard must ignore records from another target."""
    import json

    asin = "B0ENV00001"
    _seed_prepared(asin)
    path = ebay_listing.listing_state_path(asin)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "env": "production",
                "status": "published",
                "offer_id": "OFF-PROD",
                "listing_id": "1100PROD",
            }
        ),
        encoding="utf-8",
    )

    items = prepared_mod.list_prepared()

    assert [item["asin"] for item in items] == [asin], items
    assert items[0]["ebay_status"] == "none"
    assert items[0]["offer_id"] == ""


def test_list_prepared_age_days_uses_prepared_at(client, monkeypatch):
    """M5: age_days must be derived from the stored prepared timestamp."""
    from datetime import datetime, timezone

    asin = "B0AGE00001"
    _seed_prepared(asin)
    with db.connect() as conn:
        conn.execute(
            "UPDATE candidates SET updated_at = ? WHERE asin = ?",
            ("2026-10-25T00:00:00+00:00", asin),
        )

    items = prepared_mod.list_prepared(
        now=datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)
    )

    assert [item["asin"] for item in items] == [asin]
    assert items[0]["age_days"] == 2.5


def test_prepared_overview_sorts_newest_first(client, monkeypatch):
    """M6: the overview is explicitly sorted by prepared_at descending."""
    from datetime import datetime, timezone

    old = {
        "asin": "B0SORT0001",
        "listing_draft": {"title": "old draft"},
        "updated_at": "2026-10-20T00:00:00+00:00",
        "ebay_price": 50.0,
        "amazon_total": 20.0,
        "margin": {},
    }
    new = {
        "asin": "B0SORT0002",
        "listing_draft": {"title": "new draft"},
        "updated_at": "2026-10-26T00:00:00+00:00",
        "ebay_price": 50.0,
        "amazon_total": 20.0,
        "margin": {},
    }
    # Deliberately ascending, unlike the DB query, to prove the explicit sort.
    monkeypatch.setattr(prepared_mod, "list_candidates", lambda limit=0: [old, new])

    items = prepared_mod.list_prepared(
        now=datetime(2026, 10, 27, tzinfo=timezone.utc)
    )

    assert [item["asin"] for item in items] == ["B0SORT0002", "B0SORT0001"]


def test_publish_mode_retries_unreachable_row(client, monkeypatch):
    """A transient Amazon reset during a publish run is retried, then published."""
    asin = "B0PUBRET01"
    _seed_prepared(asin)
    calls = _install_stubs(monkeypatch)
    monkeypatch.setattr(upload_items, "RETRY_PASS_PAUSE_SEC", 0)
    seen = {"n": 0}

    def flaky_offers(fetched: str) -> list[OfferIn]:
        calls["fetch"].append(fetched)
        seen["n"] += 1
        if seen["n"] == 1:
            raise upload_items.AmazonUnreachable(
                "AMAZON_UNREACHABLE: ASIN B0PUBRET01 failed after 3 attempts: "
                "ERR_CONNECTION_RESET"
            )
        return [_offer(fetched)]

    monkeypatch.setattr(upload_items, "fetch_variation_offers", flaky_offers)

    r = client.post("/api/prepared/publish", json={"asins": [asin]})
    assert r.status_code == 200
    status = _wait_done(client)

    row = status["rows"][0]
    assert row["state"] == "published"
    assert row["attempts"] == 2
    assert calls["fetch"] == [asin, asin]
    assert calls["publish"] == [asin]


def test_list_prepared_has_no_env_parameter():
    """The overview always uses the current target; no env argument remains."""
    with pytest.raises(TypeError):
        prepared_mod.list_prepared("sandbox")
