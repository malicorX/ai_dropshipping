"""Upload-items file pipeline: parser, production gate, sequential job, dedupe."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import dropship_desk.api as api_mod
import dropship_desk.upload_items as upload_items
from dropship_desk import config as cfg
from dropship_desk.ebay import client as ebay_http
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


def _install_stubs(
    monkeypatch,
    *,
    missing=(),
    fetch_hook=None,
    variation_hook=None,
    draft_title=None,
    draft_title_hook=None,
):
    calls: dict[str, list] = {
        "fetch": [],
        "evaluate": [],
        "draft": [],
        "stage": [],
        "stage_patch": [],
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
        title = draft_title_hook(asin) if draft_title_hook is not None else draft_title
        return {
            "asin": asin,
            "draft": {
                "title": title if title is not None else f"eBay title {asin}",
                "description_html": "<p>copy</p>",
                "bullet_points": ["one"],
            },
            "media": {},
            "artifacts": {},
        }

    def fake_stage(asin, draft_patch=None):
        calls["stage"].append(asin)
        calls["stage_patch"].append((asin, draft_patch))
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

    def fake_variations(asin: str) -> list[OfferIn]:
        if variation_hook is not None:
            return variation_hook(asin)
        return [fake_fetch(asin)]

    monkeypatch.setattr(upload_items, "fetch_variation_offers", fake_variations)
    monkeypatch.setattr(upload_items, "run_evaluate", fake_evaluate)
    monkeypatch.setattr(upload_items, "generate_draft", fake_draft)
    monkeypatch.setattr(upload_items.ebay_listing, "stage_unpublished", fake_stage)
    monkeypatch.setattr(upload_items.ebay_listing, "publish_offer", fake_publish)
    return calls


def _install_http_stub(monkeypatch) -> list[tuple]:
    """Replace httpx.Client so any real transport attempt is observable."""
    calls: list[tuple] = []

    class _Response:
        status_code = 200
        content = b"{}"
        text = "{}"

        def json(self):
            return {}

    class _Client:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc_info) -> bool:
            return False

        def request(self, *args, **kwargs):
            calls.append(("request", args, kwargs))
            return _Response()

        def post(self, *args, **kwargs):
            calls.append(("post", args, kwargs))
            return _Response()

    monkeypatch.setattr(ebay_http.httpx, "Client", _Client)
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
    assert cfg.upload_sandbox_pinned() is False


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
    clock = {"t": 20.0}
    monkeypatch.setattr(upload_items, "_monotonic", lambda: clock["t"])

    def broken_fetch(asin: str) -> OfferIn:
        clock["t"] = 24.0
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
    # The aborted row must still record how long it ran before the systemic
    # Chrome failure stopped the batch.
    assert status["rows"][0]["started_at"]
    assert status["rows"][0]["finished_at"]
    assert status["rows"][0]["duration_sec"] == 4.0
    assert status["rows"][1]["duration_sec"] is None
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
    assert cfg.upload_sandbox_pinned() is False


def test_target_changed_abort_stamps_row_duration(client, tmp_path, monkeypatch):
    holder = {"env": "sandbox"}
    clock = {"t": 10.0}
    monkeypatch.setattr(cfg, "ebay_env", lambda: holder["env"])
    monkeypatch.setattr(upload_items, "_monotonic", lambda: clock["t"])

    def flipping_fetch(asin: str) -> OfferIn:
        holder["env"] = "production"
        clock["t"] = 13.0
        return _offer(asin)

    _install_stubs(monkeypatch, fetch_hook=flipping_fetch)
    _write_upload(tmp_path, monkeypatch, "https://www.amazon.de/dp/B0TARGET02\n")

    client.post("/api/upload-items/start")
    status = _wait_done(client)

    row = status["rows"][0]
    assert status["phase"] == "aborted_target_changed"
    # The row had already reached "evaluated" before the target check; the
    # abort path keeps that state but must stamp the elapsed duration/reason.
    assert row["state"] in {"evaluated", "error"}
    assert row["reason"].startswith("aborted_target_changed")
    assert row["started_at"]
    assert row["finished_at"]
    assert row["duration_sec"] == 3.0


def test_target_switch_to_production_is_409_while_upload_running(client, tmp_path, monkeypatch):
    started = threading.Event()
    release = threading.Event()
    pin_seen = {"value": None}

    def blocking_fetch(asin: str) -> OfferIn:
        pin_seen["value"] = cfg.upload_sandbox_pinned()
        started.set()
        assert release.wait(timeout=10)
        return _offer(asin)

    _install_stubs(monkeypatch, fetch_hook=blocking_fetch)
    _write_upload(tmp_path, monkeypatch, "https://www.amazon.de/dp/B0LOCK0001\n")

    try:
        assert client.post("/api/upload-items/start").status_code == 200
        assert started.wait(timeout=5)
        assert pin_seen["value"] is True

        live = client.post("/api/ebay/target", json={"env": "production"})
        assert live.status_code == 409
        assert live.json()["code"] == "UPLOAD_RUNNING"
        assert "UPLOAD_RUNNING" in live.json()["detail"]

        sandbox = client.post("/api/ebay/target", json={"env": "sandbox"})
        assert sandbox.status_code == 200
    finally:
        release.set()
    status = _wait_done(client)
    assert status["rows"][0]["state"] == "published"
    assert cfg.upload_sandbox_pinned() is False


def test_oauth_callback_to_production_is_409_while_upload_running(
    client, tmp_path, monkeypatch
):
    started = threading.Event()
    release = threading.Event()

    def blocking_fetch(asin: str) -> OfferIn:
        started.set()
        assert release.wait(timeout=10)
        return _offer(asin)

    _install_stubs(monkeypatch, fetch_hook=blocking_fetch)
    _write_upload(tmp_path, monkeypatch, "https://www.amazon.de/dp/B0LOCK0002\n")
    monkeypatch.setattr(cfg, "ebay_target_ready", lambda env=None: True)
    exchange_calls: list[str] = []

    def fake_exchange(code: str) -> dict:
        exchange_calls.append(code)
        return {}

    monkeypatch.setattr(upload_items.ebay_oauth, "exchange_code", fake_exchange)

    try:
        assert client.post("/api/upload-items/start").status_code == 200
        assert started.wait(timeout=5)

        switched = client.get(
            "/api/ebay/oauth/callback?code=x&state=production"
        )
        assert switched.status_code == 409
        assert switched.json()["code"] == "UPLOAD_RUNNING"
        assert "UPLOAD_RUNNING" in switched.json()["detail"]
        # The callback must not exchange a production code or flip the target.
        assert exchange_calls == []
        assert cfg._ebay_env_override is None
    finally:
        release.set()
    status = _wait_done(client)
    assert status["rows"][0]["state"] == "published"


def test_oauth_callback_to_sandbox_is_allowed_while_upload_running(
    client, tmp_path, monkeypatch
):
    started = threading.Event()
    release = threading.Event()

    def blocking_fetch(asin: str) -> OfferIn:
        started.set()
        assert release.wait(timeout=10)
        return _offer(asin)

    _install_stubs(monkeypatch, fetch_hook=blocking_fetch)
    _write_upload(tmp_path, monkeypatch, "https://www.amazon.de/dp/B0LOCK0003\n")
    monkeypatch.setattr(cfg, "ebay_target_ready", lambda env=None: True)
    exchange_calls: list[str] = []

    def fake_exchange(code: str) -> dict:
        exchange_calls.append(code)
        return {}

    monkeypatch.setattr(upload_items.ebay_oauth, "exchange_code", fake_exchange)

    try:
        assert client.post("/api/upload-items/start").status_code == 200
        assert started.wait(timeout=5)

        allowed = client.get("/api/ebay/oauth/callback?code=x&state=sandbox")
        assert allowed.status_code == 200
        assert exchange_calls == ["x"]
    finally:
        release.set()
    status = _wait_done(client)
    assert status["rows"][0]["state"] == "published"


def test_pin_released_after_worker_crash(client, tmp_path, monkeypatch):
    def crashing_process(self, row):
        raise RuntimeError("worker crash")

    _install_stubs(monkeypatch)
    monkeypatch.setattr(upload_items.UploadJobManager, "_process_row", crashing_process)
    _write_upload(tmp_path, monkeypatch, "https://www.amazon.de/dp/B0CRASH001\n")

    client.post("/api/upload-items/start")
    status = _wait_done(client)

    assert status["running"] is False
    assert status["phase"] == "aborted"
    assert "worker crash" in status["error"]
    assert cfg.upload_sandbox_pinned() is False


def _flipping_check(monkeypatch, holder, flip_after: int):
    real_check = upload_items.UploadJobManager._check_target

    def flipping_check(self):
        real_check(self)
        holder["checks"] += 1
        if holder["checks"] == flip_after:
            holder["env"] = "production"

    monkeypatch.setattr(upload_items.UploadJobManager, "_check_target", flipping_check)


def test_env_flip_after_stage_check_is_blocked_by_transport(client, tmp_path, monkeypatch):
    holder = {"env": "sandbox", "checks": 0}
    monkeypatch.setattr(cfg, "ebay_env", lambda: holder["env"])
    calls = _install_stubs(monkeypatch)
    http_calls = _install_http_stub(monkeypatch)
    stage_attempts: list[str] = []

    def transport_stage(asin):
        stage_attempts.append(asin)
        return ebay_http.request(
            "PUT", f"/sell/inventory/v1/inventory_item/DD-{asin}", json_body={}
        )

    monkeypatch.setattr(upload_items.ebay_listing, "stage_unpublished", transport_stage)
    _flipping_check(monkeypatch, holder, flip_after=2)
    _write_upload(tmp_path, monkeypatch, "https://www.amazon.de/dp/B0FLIP0001\n")

    client.post("/api/upload-items/start")
    status = _wait_done(client)

    assert status["phase"] == "aborted_target_changed"
    assert holder["checks"] == 2
    assert stage_attempts == ["B0FLIP0001"]
    assert http_calls == []
    assert calls["publish"] == []
    assert cfg.upload_sandbox_pinned() is False


def test_env_flip_after_publish_check_is_blocked_by_transport(client, tmp_path, monkeypatch):
    holder = {"env": "sandbox", "checks": 0}
    monkeypatch.setattr(cfg, "ebay_env", lambda: holder["env"])
    calls = _install_stubs(monkeypatch)
    http_calls = _install_http_stub(monkeypatch)
    publish_attempts: list[str] = []

    def transport_publish(asin):
        publish_attempts.append(asin)
        return ebay_http.request("POST", f"/sell/inventory/v1/offer/OFF-{asin}/publish")

    monkeypatch.setattr(upload_items.ebay_listing, "publish_offer", transport_publish)
    _flipping_check(monkeypatch, holder, flip_after=3)
    _write_upload(tmp_path, monkeypatch, "https://www.amazon.de/dp/B0FLIP0002\n")

    client.post("/api/upload-items/start")
    status = _wait_done(client)

    assert status["phase"] == "aborted_target_changed"
    assert holder["checks"] == 3
    assert calls["stage"] == ["B0FLIP0002"]
    assert publish_attempts == ["B0FLIP0002"]
    assert http_calls == []
    assert cfg.upload_sandbox_pinned() is False


def test_variation_parent_is_rejected_and_never_staged(client, tmp_path, monkeypatch):
    parent = "B0PARENT01"

    def parent_offers(asin: str) -> list[OfferIn]:
        assert asin == parent
        return [_offer("B0CHILD001"), _offer("B0CHILD002")]

    calls = _install_stubs(monkeypatch, variation_hook=parent_offers)
    _write_upload(tmp_path, monkeypatch, f"https://www.amazon.de/dp/{parent}\n")

    client.post("/api/upload-items/start")
    status = _wait_done(client)

    row = status["rows"][0]
    assert row["state"] == "rejected"
    assert row["reason"] == "variation_parent"
    assert status["phase"] == "finished"
    assert calls["evaluate"] == []
    assert calls["draft"] == []
    assert calls["stage"] == []
    assert calls["publish"] == []


def test_genuine_variation_child_passes(client, tmp_path, monkeypatch):
    child = "B0CHILD001"

    def child_offers(asin: str) -> list[OfferIn]:
        assert asin == child
        child_offer = _offer(child).model_copy(
            update={"parent_asin": "B0PARENT01", "variation_label": "20 kg"}
        )
        sibling = _offer("B0SIBL0002").model_copy(
            update={"parent_asin": "B0PARENT01", "variation_label": "40 kg"}
        )
        return [child_offer, sibling]

    calls = _install_stubs(monkeypatch, variation_hook=child_offers)
    _write_upload(tmp_path, monkeypatch, f"https://www.amazon.de/dp/{child}\n")

    client.post("/api/upload-items/start")
    status = _wait_done(client)

    assert status["rows"][0]["state"] == "published"
    assert calls["evaluate"] == [(child, "always")]
    assert calls["stage"] == [child]


def test_missing_variation_label_is_patched_before_stage(client, tmp_path, monkeypatch):
    child = "B0VAR00001"

    def child_offers(_asin: str) -> list[OfferIn]:
        return [
            _offer(child).model_copy(
                update={"parent_asin": "B0PARENT05", "variation_label": "Red / G2"}
            )
        ]

    calls = _install_stubs(
        monkeypatch,
        variation_hook=child_offers,
        draft_title=f"eBay title {child}",
    )
    _write_upload(tmp_path, monkeypatch, f"https://www.amazon.de/dp/{child}\n")

    client.post("/api/upload-items/start")
    status = _wait_done(client)

    assert status["rows"][0]["state"] == "published"
    assert calls["stage"] == [child]
    # The title is fixed deterministically; there is no second LLM draft.
    assert calls["draft"] == [child]
    assert calls["stage_patch"] == [(child, {"title": f"eBay title {child} - Red / G2"})]


def test_present_variation_label_leaves_title_unchanged(client, tmp_path, monkeypatch):
    child = "B0VAR00002"
    draft_title = f"eBay title {child} – Red / G2"

    def child_offers(_asin: str) -> list[OfferIn]:
        return [
            _offer(child).model_copy(
                update={"parent_asin": "B0PARENT06", "variation_label": "Red / G2"}
            )
        ]

    calls = _install_stubs(
        monkeypatch,
        variation_hook=child_offers,
        draft_title=draft_title,
    )
    _write_upload(tmp_path, monkeypatch, f"https://www.amazon.de/dp/{child}\n")

    client.post("/api/upload-items/start")
    status = _wait_done(client)

    assert status["rows"][0]["state"] == "published"
    assert calls["stage"] == [child]
    assert calls["stage_patch"] == [(child, None)]


def test_present_variation_label_is_case_insensitive(client, tmp_path, monkeypatch):
    child = "B0VAR00004"
    draft_title = f"eBay title {child} – red / g2"

    def child_offers(_asin: str) -> list[OfferIn]:
        return [
            _offer(child).model_copy(
                update={"parent_asin": "B0PARENT08", "variation_label": "Red / G2"}
            )
        ]

    calls = _install_stubs(
        monkeypatch,
        variation_hook=child_offers,
        draft_title=draft_title,
    )
    _write_upload(tmp_path, monkeypatch, f"https://www.amazon.de/dp/{child}\n")

    client.post("/api/upload-items/start")
    status = _wait_done(client)

    assert status["rows"][0]["state"] == "published"
    # The label is already present with different casing, so no title patch
    # may be added (a case-sensitive check would append it a second time).
    assert calls["stage_patch"] == [(child, None)]


def test_title_with_variation_matches_label_case_insensitively():
    title = "eBay title B0VAR00005 – red / g2"
    assert upload_items.title_with_variation(title, "Red / G2") == title


def test_long_title_is_clipped_around_variation_label(client, tmp_path, monkeypatch):
    child = "B0VAR00003"
    long_title = "Langes Produkt " + ("x" * 120)

    def child_offers(_asin: str) -> list[OfferIn]:
        return [
            _offer(child).model_copy(
                update={"parent_asin": "B0PARENT07", "variation_label": "Red / G2"}
            )
        ]

    calls = _install_stubs(
        monkeypatch,
        variation_hook=child_offers,
        draft_title=long_title,
    )
    _write_upload(tmp_path, monkeypatch, f"https://www.amazon.de/dp/{child}\n")

    client.post("/api/upload-items/start")
    status = _wait_done(client)

    assert status["rows"][0]["state"] == "published"
    patch = calls["stage_patch"][0][1]
    assert patch is not None
    title = patch["title"]
    assert len(title) <= 80
    assert title.endswith(" - Red / G2")
    assert "Red / G2" in title


def test_rows_record_monotonic_durations_for_published_and_error(
    client, tmp_path, monkeypatch
):
    clock = {"t": 100.0}
    monkeypatch.setattr(upload_items, "_monotonic", lambda: clock["t"])

    def timed_fetch(asin: str) -> OfferIn:
        if asin == "B0DUR00001":
            clock["t"] = 105.0
            return _offer(asin)
        clock["t"] = 112.0
        raise upload_items.AmazonUnreachable(
            "AMAZON_UNREACHABLE: ASIN B0DUR00002 failed after 3 attempts"
        )

    _install_stubs(monkeypatch, fetch_hook=timed_fetch)
    _write_upload(
        tmp_path,
        monkeypatch,
        "https://www.amazon.de/dp/B0DUR00001\nhttps://www.amazon.de/dp/B0DUR00002\n",
    )

    client.post("/api/upload-items/start")
    status = _wait_done(client)

    first, second = status["rows"]
    assert first["state"] == "published"
    assert first["duration_sec"] == 5.0
    assert first["started_at"]
    assert first["finished_at"]
    assert second["state"] == "error"
    assert second["duration_sec"] == 7.0
    assert second["started_at"]
    assert second["finished_at"]


def test_skipped_existing_row_records_near_zero_duration(
    client, tmp_path, monkeypatch
):
    clock = {"t": 50.0}
    monkeypatch.setattr(upload_items, "_monotonic", lambda: clock["t"])
    _install_stubs(monkeypatch)
    _seed_published("B0SKIP0001", "1100B0SKIP0001")
    _write_upload(tmp_path, monkeypatch, "https://www.amazon.de/dp/B0SKIP0001\n")

    client.post("/api/upload-items/start")
    status = _wait_done(client)

    row = status["rows"][0]
    assert row["state"] == "skipped_existing"
    assert row["duration_sec"] == 0.0
    assert row["started_at"]
    assert row["finished_at"]


def test_variation_parent_with_only_one_child_is_rejected(
    client, tmp_path, monkeypatch
):
    parent = "B0PARENT02"

    def one_child(_asin: str) -> list[OfferIn]:
        return [_offer("B0ONECHILD")]

    calls = _install_stubs(monkeypatch, variation_hook=one_child)
    _write_upload(tmp_path, monkeypatch, f"https://www.amazon.de/dp/{parent}\n")

    client.post("/api/upload-items/start")
    status = _wait_done(client)

    row = status["rows"][0]
    assert row["state"] == "rejected"
    assert row["reason"] == "variation_parent"
    assert status["phase"] == "finished"
    assert calls["evaluate"] == []
    assert calls["draft"] == []
    assert calls["stage"] == []
    assert calls["publish"] == []


def test_variation_parent_with_no_fetched_children_is_rejected(
    client, tmp_path, monkeypatch
):
    parent = "B0PARENT03"

    class _IncompleteScan(list):
        # Mirrors the product helper's metadata: the PDP reported variations
        # but every child fetch failed, so only the parent snapshot is left.
        reported_variations = True
        children_fetched = 0

    def no_children(_asin: str) -> list[OfferIn]:
        return _IncompleteScan([_offer(parent)])

    calls = _install_stubs(monkeypatch, variation_hook=no_children)
    _write_upload(tmp_path, monkeypatch, f"https://www.amazon.de/dp/{parent}\n")

    client.post("/api/upload-items/start")
    status = _wait_done(client)

    row = status["rows"][0]
    assert row["state"] == "rejected"
    assert row["reason"] == "variation_parent"
    assert calls["evaluate"] == []
    assert calls["stage"] == []
    assert calls["publish"] == []


def test_genuine_variation_child_with_one_offer_passes(
    client, tmp_path, monkeypatch
):
    child = "B0CHILD001"

    def child_only(asin: str) -> list[OfferIn]:
        assert asin == child
        return [
            _offer(child).model_copy(
                update={"parent_asin": "B0PARENT04", "variation_label": "20 kg"}
            )
        ]

    calls = _install_stubs(monkeypatch, variation_hook=child_only)
    _write_upload(tmp_path, monkeypatch, f"https://www.amazon.de/dp/{child}\n")

    client.post("/api/upload-items/start")
    status = _wait_done(client)

    assert status["rows"][0]["state"] == "published"
    assert calls["stage"] == [child]


def test_plain_product_with_one_matching_offer_passes(
    client, tmp_path, monkeypatch
):
    product = "B0PLAIN001"
    calls = _install_stubs(monkeypatch)
    _write_upload(tmp_path, monkeypatch, f"https://www.amazon.de/dp/{product}\n")

    client.post("/api/upload-items/start")
    status = _wait_done(client)

    assert status["rows"][0]["state"] == "published"
    assert calls["stage"] == [product]


def test_ordinary_amazon_unreachable_is_a_row_error_and_run_continues(client, tmp_path, monkeypatch):
    def flaky_fetch(asin: str) -> OfferIn:
        if asin == "B0FLAKY001":
            raise upload_items.AmazonUnreachable(
                "AMAZON_UNREACHABLE: ASIN B0FLAKY001 failed after 3 attempts"
            )
        return _offer(asin)

    calls = _install_stubs(monkeypatch, fetch_hook=flaky_fetch)
    _write_upload(
        tmp_path,
        monkeypatch,
        "https://www.amazon.de/dp/B0FLAKY001\nhttps://www.amazon.de/dp/B0AFTER001\n",
    )

    client.post("/api/upload-items/start")
    status = _wait_done(client)

    assert [row["state"] for row in status["rows"]] == ["error", "published"]
    assert status["phase"] == "finished"
    assert calls["stage"] == ["B0AFTER001"]
    assert calls["publish"] == ["B0AFTER001"]


def _seed_published(asin: str, listing_id: str) -> None:
    ebay_listing.save_listing_state(
        asin,
        {
            "status": "published",
            "offer_id": f"OFF-{asin}",
            "listing_id": listing_id,
        },
    )


def test_published_rows_are_marked_before_any_fetch(client, tmp_path, monkeypatch):
    calls = _install_stubs(monkeypatch)
    _seed_published("B0MARK0001", "1100B0MARK0001")
    _seed_published("B0MARK0002", "1100B0MARK0002")
    _write_upload(
        tmp_path,
        monkeypatch,
        "\n".join(
            [
                "https://www.amazon.de/dp/B0MARK0001",
                "https://www.amazon.de/dp/B0MARK0002",
                "https://www.amazon.de/dp/B0MARK0003",
            ]
        )
        + "\n",
    )

    client.post("/api/upload-items/start")
    status = _wait_done(client)

    rows = status["rows"]
    assert [row["state"] for row in rows] == [
        "skipped_existing",
        "skipped_existing",
        "published",
    ]
    assert [row["reason"] for row in rows[:2]] == ["haben wir schon", "haben wir schon"]
    assert rows[0]["offer_id"] == "OFF-B0MARK0001"
    assert rows[0]["listing_id"] == "1100B0MARK0001"
    assert rows[0]["item_url"] == "https://www.sandbox.ebay.com/itm/1100B0MARK0001"
    assert rows[1]["offer_id"] == "OFF-B0MARK0002"
    assert rows[1]["listing_id"] == "1100B0MARK0002"
    # The known ASINs must not cost a single fetch/evaluate/draft/stage/publish.
    assert calls["fetch"] == ["B0MARK0003"]
    assert calls["evaluate"] == [("B0MARK0003", "always")]
    assert calls["draft"] == ["B0MARK0003"]
    assert calls["stage"] == ["B0MARK0003"]
    assert calls["publish"] == ["B0MARK0003"]


def test_unpublished_saved_state_is_not_marked_already_listed(
    client, tmp_path, monkeypatch
):
    asin = "B0STAGED01"
    calls = _install_stubs(monkeypatch)
    # A staged but never published offer keeps status "unpublished".  It must
    # not short-circuit the run as "haben wir schon"; the row still has to be
    # fetched, processed and published.
    ebay_listing.save_listing_state(
        asin,
        {"status": "unpublished", "offer_id": f"OFF-{asin}", "listing_id": ""},
    )
    _write_upload(tmp_path, monkeypatch, f"https://www.amazon.de/dp/{asin}\n")

    client.post("/api/upload-items/start")
    status = _wait_done(client)

    row = status["rows"][0]
    assert row["state"] == "published"
    assert row["reason"] == ""
    assert calls["fetch"] == [asin]
    assert calls["stage"] == [asin]
    assert calls["publish"] == [asin]


def test_state_published_between_fetch_and_stage_is_rechecked(
    client, tmp_path, monkeypatch
):
    asin = "B0RECHECK1"

    def publish_during_fetch(fetched_asin: str) -> OfferIn:
        # The pre-fetch check already passed (the state was absent), then the
        # listing becomes published while Amazon is being fetched.  The final
        # re-check before staging must notice it and stage nothing.
        ebay_listing.save_listing_state(
            fetched_asin,
            {
                "status": "published",
                "offer_id": f"OFF-{fetched_asin}",
                "listing_id": f"1100{fetched_asin}",
            },
        )
        return _offer(fetched_asin)

    calls = _install_stubs(monkeypatch, fetch_hook=publish_during_fetch)
    _write_upload(tmp_path, monkeypatch, f"https://www.amazon.de/dp/{asin}\n")

    client.post("/api/upload-items/start")
    status = _wait_done(client)

    row = status["rows"][0]
    assert row["state"] == "skipped_existing"
    assert row["reason"] == "haben wir schon"
    assert row["offer_id"] == f"OFF-{asin}"
    assert row["listing_id"] == f"1100{asin}"
    assert calls["fetch"] == [asin]
    assert calls["stage"] == []
    assert calls["publish"] == []


def test_legacy_sandbox_state_with_production_env_is_not_already_listed(
    client, tmp_path, monkeypatch
):
    asin = "B0LEGACY01"
    calls = _install_stubs(monkeypatch)
    # Old records wrote a single state file and kept the env inside it.  The
    # sandbox file here claims it belongs to production, so a sandbox run must
    # ignore it and process the ASIN instead of marking it "haben wir schon".
    path = ebay_listing.listing_state_path(asin)
    assert path.name == "ebay_sandbox.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "status": "published",
                "env": "production",
                "offer_id": f"OFF-{asin}",
                "listing_id": f"1100{asin}",
            }
        ),
        encoding="utf-8",
    )
    _write_upload(tmp_path, monkeypatch, f"https://www.amazon.de/dp/{asin}\n")

    client.post("/api/upload-items/start")
    status = _wait_done(client)

    row = status["rows"][0]
    assert row["state"] == "published"
    assert calls["fetch"] == [asin]
    assert calls["stage"] == [asin]
    assert calls["publish"] == [asin]


def test_preview_marks_published_rows_as_already_listed(client, tmp_path, monkeypatch):
    calls = _install_stubs(monkeypatch)
    _seed_published("B0MARK0001", "1100B0MARK0001")
    _seed_published("B0MARK0002", "1100B0MARK0002")
    _write_upload(
        tmp_path,
        monkeypatch,
        "\n".join(
            [
                "https://www.amazon.de/dp/B0MARK0001",
                "https://www.amazon.de/dp/B0MARK0002",
                "https://www.amazon.de/dp/B0MARK0003",
            ]
        )
        + "\n",
    )

    r = client.get("/api/upload-items/preview")

    assert r.status_code == 200
    rows = r.json()["rows"]
    assert [row["state"] for row in rows] == [
        "already_listed",
        "already_listed",
        "queued",
    ]
    assert [row["reason"] for row in rows[:2]] == ["haben wir schon", "haben wir schon"]
    assert rows[0]["offer_id"] == "OFF-B0MARK0001"
    assert rows[0]["listing_id"] == "1100B0MARK0001"
    assert rows[0]["item_url"] == "https://www.sandbox.ebay.com/itm/1100B0MARK0001"
    assert rows[2]["offer_id"] == ""
    # Preview is file-only: it must not touch Amazon or eBay transports.
    for name, seen in calls.items():
        assert seen == [], f"{name} was called by preview: {seen}"


def test_failure_cap_amazon_unreachable_aborts_the_run(client, tmp_path, monkeypatch):
    clock = {"t": 30.0}
    monkeypatch.setattr(upload_items, "_monotonic", lambda: clock["t"])

    def capped_fetch(asin: str) -> OfferIn:
        clock["t"] = 35.0
        raise upload_items.AmazonUnreachable(
            "AMAZON_UNREACHABLE: failure cap reached after 20 consecutive terminal failures"
        )

    calls = _install_stubs(monkeypatch, fetch_hook=capped_fetch)
    _write_upload(
        tmp_path,
        monkeypatch,
        "https://www.amazon.de/dp/B0CAP00001\nhttps://www.amazon.de/dp/B0CAP00002\n",
    )

    client.post("/api/upload-items/start")
    status = _wait_done(client)

    assert status["phase"] == "aborted"
    assert "failure cap" in status["error"]
    assert status["rows"][0]["state"] == "error"
    assert status["rows"][1]["state"] == "queued"
    assert status["rows"][0]["started_at"]
    assert status["rows"][0]["finished_at"]
    assert status["rows"][0]["duration_sec"] == 5.0
    assert status["rows"][1]["duration_sec"] is None
    assert calls["stage"] == []
    assert calls["publish"] == []
