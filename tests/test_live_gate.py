"""Guarded production (live) upload/publish path.

All tests are local-only.  Amazon, evaluate and the LLM draft are stubs; the
eBay transport is either a spy or the config-level host guard.  No test may
make a network call or a real eBay write.
"""

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
from dropship_desk import db
from dropship_desk.ebay import client as ebay_http
from dropship_desk.ebay import listing as ebay_listing
from dropship_desk.models import EvaluateResponse, OfferIn

ASIN_A = "B0LIVE0001"
ASIN_B = "B0LIVE0002"
FILE_A = "https://www.amazon.de/dp/B0LIVE0001\n"
FILE_B = "https://www.amazon.de/dp/B0LIVE0002\n"
TWO_LINES = FILE_A + FILE_B


def _write_upload(tmp_path: Path, monkeypatch, text: str, name: str = "upload_items.txt") -> Path:
    path = tmp_path / name
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
    fetch_hook=None,
    variation_hook=None,
    evaluate_passed: bool = True,
    stage_hook=None,
):
    calls: dict[str, list] = {
        "fetch": [],
        "evaluate": [],
        "draft": [],
        "stage": [],
        "publish": [],
        "pin": [],
    }

    def fake_fetch(asin: str) -> OfferIn:
        calls["fetch"].append(asin)
        if fetch_hook is not None:
            return fetch_hook(asin)
        return _offer(asin)

    def fake_evaluate(body, *, persist=None):
        calls["evaluate"].append((body.asin_or_url, persist, body.ebay_price))
        offer = body.offer
        margin = {"passed": evaluate_passed, "fail_reasons": [] if evaluate_passed else ["thin"]}
        return EvaluateResponse(
            asin=offer.asin,
            offer=offer,
            ebay_price=50.0,
            max_amazon_buy=offer.amazon_total,
            suggested_ebay_price=50.0,
            passed=evaluate_passed,
            hard_reject_reasons=[],
            margin=margin,
            candidate_id=1,
            status="ready" if evaluate_passed else "rejected",
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

    def fake_stage(asin, draft_patch=None, **kwargs):
        calls["stage"].append(asin)
        calls.setdefault("stage_kwargs", []).append(dict(kwargs))
        calls["pin"].append(cfg.production_live_pinned())
        ebay_listing.save_listing_state(
            asin,
            {"status": "unpublished", "offer_id": f"OFF-{asin}", "listing_id": ""},
        )
        if stage_hook is not None:
            stage_hook(asin)
        return ebay_listing.public_listing(asin)

    def fake_publish(asin):
        calls["publish"].append(asin)
        calls["pin"].append(cfg.production_live_pinned())
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
    monkeypatch.setattr(upload_items.ebay_oauth, "oauth_connected", lambda env=None: True)
    monkeypatch.setattr(api_mod, "UPLOAD_JOB", upload_items.UploadJobManager())
    return TestClient(api_mod.create_app())


def _live_env(
    monkeypatch,
    *,
    env: str = "production",
    flag: bool = True,
    automation: bool = True,
    allow_list: bool = True,
    connected: bool = True,
    cap: int = 5,
) -> None:
    monkeypatch.setattr(cfg, "ebay_env", lambda: env)
    monkeypatch.setenv("EBAY_LIVE_UPLOAD_ENABLED", "true" if flag else "false")
    monkeypatch.setenv("EBAY_AUTOMATION_ENABLED", "true" if automation else "false")
    monkeypatch.setenv("EBAY_ALLOW_LIST", "true" if allow_list else "false")
    monkeypatch.setenv("EBAY_LIVE_MAX_PER_RUN", str(cap))
    monkeypatch.setattr(
        upload_items.ebay_oauth,
        "oauth_connected",
        lambda target=None: connected if (target or env) == "production" else True,
    )


def _plan(client: TestClient, mode: str, **extra) -> dict:
    response = client.post("/api/live/plan", json={"mode": mode, **extra})
    assert response.status_code == 200, response.text
    return response.json()


_UNSET = object()


def _upload_live(
    client: TestClient,
    plan: dict,
    *,
    file_name: str = "upload_items.txt",
    confirm="LIVE 2",
    batch_hash=_UNSET,
    **extra,
):
    body = {
        "mode": "full",
        "file": file_name,
        "confirm": confirm,
        "batch_hash": (
            plan["batch_hash"] if batch_hash is _UNSET else batch_hash
        ),
        "plan_nonce": plan.get("nonce", ""),
        **extra,
    }
    return client.post("/api/upload-items/start", json=body)


def _wait_done(client: TestClient, timeout: float = 10.0) -> dict:
    deadline = time.time() + timeout
    last: dict = {}
    while time.time() < deadline:
        last = client.get("/api/upload-items/status").json()
        if not last.get("running"):
            return last
        time.sleep(0.01)
    raise AssertionError(f"upload job did not finish: {last}")


def _audit_lines(tmp_path: Path) -> list[dict]:
    path = tmp_path / "live_audit.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _seed_prepared(asin: str, *, price: float = 50.0) -> None:
    db.upsert_candidate(
        asin=asin,
        title=f"Amazon {asin}",
        amazon_total=20.0,
        ebay_price=price,
        max_amazon_buy=20.0,
        status="ready",
        offer={"title": f"Amazon {asin}"},
        margin={"passed": True, "fail_reasons": [], "margin_pct": 0.55},
        hard_reject=[],
    )
    db.save_listing_draft(
        asin,
        {
            "title": f"eBay title {asin}",
            "description_html": "<p>copy</p>",
            "bullet_points": ["one"],
        },
    )


# --------------------------------------------------------------- plan / gates


def test_live_plan_is_read_only_and_makes_no_ebay_calls(client, tmp_path, monkeypatch):
    _live_env(monkeypatch)
    calls = _install_stubs(monkeypatch)
    http_calls = _install_http_stub(monkeypatch)
    _write_upload(tmp_path, monkeypatch, TWO_LINES)

    plan = _plan(client, "upload", file="upload_items.txt")

    assert plan["n"] == 2
    assert plan["cap"] == 5
    assert plan["live_enabled"] is True
    assert plan["live_missing"] == []
    assert len(plan["batch_hash"]) == 64
    assert [item["asin"] for item in plan["items"]] == [ASIN_A, ASIN_B]
    assert set(plan["items"][0]) == {"asin", "title", "price"}
    assert "total" in plan
    for seen in calls.values():
        assert seen == [], seen
    assert http_calls == []
    assert not (tmp_path / "products").exists() or not list(
        (tmp_path / "products").rglob("ebay_production.json")
    )


def test_live_plan_binds_env_asins_and_file_content(client, tmp_path, monkeypatch):
    _live_env(monkeypatch)
    _write_upload(tmp_path, monkeypatch, TWO_LINES)
    first = _plan(client, "upload", file="upload_items.txt")

    # Same ASINs, different file bytes -> different hash.
    _write_upload(
        tmp_path,
        monkeypatch,
        "https://www.amazon.de/dp/B0LIVE0001?th=1\nhttps://www.amazon.de/dp/B0LIVE0002\n",
    )
    second = _plan(client, "upload", file="upload_items.txt")

    assert first["n"] == second["n"] == 2
    assert first["batch_hash"] != second["batch_hash"]

    # Publish plan is bound to the sorted selection.
    left = _plan(client, "publish", asins=[ASIN_B, ASIN_A])
    right = _plan(client, "publish", asins=[ASIN_A, ASIN_B])
    assert left["batch_hash"] == right["batch_hash"]
    assert left["n"] == 2


@pytest.mark.parametrize(
    ("broken", "missing_name"),
    [
        ("flag", "EBAY_LIVE_UPLOAD_ENABLED"),
        ("automation", "EBAY_AUTOMATION_ENABLED"),
        ("allow_list", "EBAY_ALLOW_LIST"),
        ("account", "EBAY_PRODUCTION_ACCOUNT"),
    ],
)
def test_each_missing_live_gate_item_is_403_with_zero_calls(
    client, tmp_path, monkeypatch, broken, missing_name
):
    _live_env(monkeypatch)
    calls = _install_stubs(monkeypatch)
    http_calls = _install_http_stub(monkeypatch)
    _write_upload(tmp_path, monkeypatch, TWO_LINES)
    plan = _plan(client, "upload", file="upload_items.txt")

    if broken == "flag":
        monkeypatch.setenv("EBAY_LIVE_UPLOAD_ENABLED", "false")
    elif broken == "automation":
        monkeypatch.setenv("EBAY_AUTOMATION_ENABLED", "false")
    elif broken == "allow_list":
        monkeypatch.setenv("EBAY_ALLOW_LIST", "false")
    else:
        monkeypatch.setattr(upload_items.ebay_oauth, "oauth_connected", lambda env=None: False)

    response = _upload_live(client, plan)

    assert response.status_code == 403, response.text
    body = response.json()
    assert body["code"] == "LIVE_UPLOAD_DISABLED"
    assert missing_name in body["missing"]
    for seen in calls.values():
        assert seen == [], seen
    assert http_calls == []
    assert client.get("/api/upload-items/status").json()["running"] is False


def test_live_gate_reports_target_env_missing(monkeypatch):
    _live_env(monkeypatch, env="sandbox")
    assert "EBAY_ENV" in upload_items.live_gate_missing("sandbox")
    assert "EBAY_ENV" not in upload_items.live_gate_missing("production")


# ------------------------------------------------------- typed confirmation


@pytest.mark.parametrize(
    "confirm",
    [None, "LIVE 1", "LIVE 99", "live 2", " LIVE 2", "LIVE 2 ", "LIVE  2", "LIVE 02", ""],
)
def test_live_confirm_must_be_exact(client, tmp_path, monkeypatch, confirm):
    _live_env(monkeypatch)
    calls = _install_stubs(monkeypatch)
    _install_http_stub(monkeypatch)
    _write_upload(tmp_path, monkeypatch, TWO_LINES)
    plan = _plan(client, "upload", file="upload_items.txt")

    response = _upload_live(client, plan, confirm=confirm)

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "LIVE_CONFIRM_MISMATCH"
    for seen in calls.values():
        assert seen == [], seen
    assert client.get("/api/upload-items/status").json()["running"] is False


def test_client_supplied_n_is_ignored(client, tmp_path, monkeypatch):
    _live_env(monkeypatch)
    calls = _install_stubs(monkeypatch)
    _write_upload(tmp_path, monkeypatch, TWO_LINES)
    plan = _plan(client, "upload", file="upload_items.txt")

    response = _upload_live(client, plan, confirm="LIVE 1", n=1)

    assert response.status_code == 409
    assert response.json()["code"] == "LIVE_CONFIRM_MISMATCH"
    for seen in calls.values():
        assert seen == [], seen


@pytest.mark.parametrize("bad_hash", [None, "", "0" * 64, "NOT-A-HASH"])
def test_live_batch_hash_must_match(client, tmp_path, monkeypatch, bad_hash):
    _live_env(monkeypatch)
    calls = _install_stubs(monkeypatch)
    _write_upload(tmp_path, monkeypatch, TWO_LINES)
    plan = _plan(client, "upload", file="upload_items.txt")

    response = _upload_live(client, plan, batch_hash=bad_hash)

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "LIVE_CONFIRM_MISMATCH"
    for seen in calls.values():
        assert seen == [], seen


def test_stale_hash_after_file_edit_is_rejected(client, tmp_path, monkeypatch):
    _live_env(monkeypatch)
    calls = _install_stubs(monkeypatch)
    path = _write_upload(tmp_path, monkeypatch, TWO_LINES)
    plan = _plan(client, "upload", file="upload_items.txt")

    # Same ASINs and line count, different bytes.
    path.write_text(
        "https://www.amazon.de/dp/B0LIVE0001?th=1\nhttps://www.amazon.de/dp/B0LIVE0002\n",
        encoding="utf-8",
    )

    response = _upload_live(client, plan, confirm="LIVE 2")

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "LIVE_CONFIRM_MISMATCH"
    for seen in calls.values():
        assert seen == [], seen


# ---------------------------------------------------------------------- cap


def test_live_cap_exceeded_is_400_and_runs_nothing(client, tmp_path, monkeypatch):
    _live_env(monkeypatch, cap=1)
    calls = _install_stubs(monkeypatch)
    _install_http_stub(monkeypatch)
    _write_upload(tmp_path, monkeypatch, TWO_LINES)
    plan = _plan(client, "upload", file="upload_items.txt")
    assert plan["n"] == 2
    assert plan["cap"] == 1

    response = _upload_live(client, plan, confirm="LIVE 2")

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "LIVE_CAP_EXCEEDED"
    for seen in calls.values():
        assert seen == [], seen


def test_live_cap_has_hard_ceiling(monkeypatch):
    monkeypatch.setenv("EBAY_LIVE_MAX_PER_RUN", "500")
    assert cfg.ebay_live_max_per_run() == 50
    monkeypatch.setenv("EBAY_LIVE_MAX_PER_RUN", "not-a-number")
    assert cfg.ebay_live_max_per_run() == 5
    monkeypatch.delenv("EBAY_LIVE_MAX_PER_RUN", raising=False)
    assert cfg.ebay_live_max_per_run() == 5


# ----------------------------------------------------------- happy live run


def test_live_happy_path_writes_planned_skus_and_audit(client, tmp_path, monkeypatch):
    _live_env(monkeypatch)
    calls = _install_stubs(monkeypatch)
    http_calls = _install_http_stub(monkeypatch)
    _write_upload(tmp_path, monkeypatch, TWO_LINES)
    plan = _plan(client, "upload", file="upload_items.txt")

    response = _upload_live(client, plan)
    assert response.status_code == 200, response.text
    status = _wait_done(client)

    assert [row["state"] for row in status["rows"]] == ["published", "published"]
    assert status["target_env"] == "production"
    assert status["live"] is True
    assert calls["stage"] == [ASIN_A, ASIN_B]
    assert calls["publish"] == [ASIN_A, ASIN_B]
    # The production pin must be active for every eBay helper call.
    assert calls["pin"] and all(calls["pin"])
    assert cfg.production_live_pinned() is False
    assert cfg.upload_sandbox_pinned() is False
    assert http_calls == []

    lines = _audit_lines(tmp_path)
    starts = [line for line in lines if line.get("event") == "start"]
    rows = {line["asin"]: line for line in lines if line.get("event") == "result"}
    assert len(starts) == 1
    assert starts[0]["n"] == 2
    assert starts[0]["batch_hash"] == plan["batch_hash"]
    assert starts[0]["cap"] == 5
    assert starts[0]["who"] == "local"
    assert set(rows) == {ASIN_A, ASIN_B}
    for asin, line in rows.items():
        assert line["run_id"] == status["run_id"]
        assert line["sku"] == f"DD-{asin}"
        assert line["state"] == "published"
        assert line["price"] == 50.0
        assert line["listing_id"] == f"1100{asin}"


def test_production_pin_allows_production_hosts_and_blocks_sandbox(monkeypatch):
    monkeypatch.setattr(cfg, "ebay_env", lambda: "production")
    monkeypatch.setenv("EBAY_LIVE_UPLOAD_ENABLED", "true")
    monkeypatch.setenv("EBAY_AUTOMATION_ENABLED", "true")
    monkeypatch.setenv("EBAY_ALLOW_LIST", "true")
    cfg.clear_live_env_cache()
    cfg.pin_production_for_live(True)
    try:
        cfg.ensure_write_target_allowed("https://api.ebay.com/sell/inventory/v1/offer")
        with pytest.raises(RuntimeError, match="LIVE_WRITE_BLOCKED"):
            cfg.ensure_write_target_allowed(
                "https://api.sandbox.ebay.com/sell/inventory/v1/offer"
            )
        monkeypatch.setattr(cfg, "ebay_env", lambda: "sandbox")
        with pytest.raises(RuntimeError, match="LIVE_WRITE_BLOCKED"):
            cfg.ensure_write_target_allowed("https://api.ebay.com/sell/inventory/v1/offer")
        # A live run blocks sandbox hosts too, even when the target flipped.
        with pytest.raises(RuntimeError, match="LIVE_WRITE_BLOCKED"):
            cfg.ensure_write_target_allowed(
                "https://api.sandbox.ebay.com/sell/inventory/v1/offer"
            )
    finally:
        cfg.pin_production_for_live(False)


def test_env_flip_mid_live_run_aborts_before_publish(client, tmp_path, monkeypatch):
    _live_env(monkeypatch)
    holder = {"env": "production"}
    monkeypatch.setattr(cfg, "ebay_env", lambda: holder["env"])
    calls = _install_stubs(
        monkeypatch,
        stage_hook=lambda asin: holder.update(env="sandbox"),
    )
    _write_upload(tmp_path, monkeypatch, TWO_LINES)
    plan = _plan(client, "upload", file="upload_items.txt")

    response = _upload_live(client, plan)
    assert response.status_code == 200, response.text
    status = _wait_done(client)

    assert status["phase"] == "aborted_target_changed"
    assert calls["stage"] == [ASIN_A]
    assert calls["publish"] == []
    assert calls["fetch"] == [ASIN_A]
    assert cfg.production_live_pinned() is False


def test_live_token_env_mismatch_aborts_like_target_change(
    client, tmp_path, monkeypatch
):
    _live_env(monkeypatch)
    calls = _install_stubs(monkeypatch)
    _write_upload(tmp_path, monkeypatch, TWO_LINES)
    plan = _plan(client, "upload", file="upload_items.txt")
    # A production token file whose record still says sandbox is a target
    # mismatch: the worker must abort before the first Amazon/eBay call.
    (tmp_path / "ebay_oauth_production.json").write_text(
        json.dumps({"refresh_token": "r", "access_token": "a", "env": "sandbox"}),
        encoding="utf-8",
    )

    response = _upload_live(client, plan)
    assert response.status_code == 200, response.text
    status = _wait_done(client)

    assert status["phase"] == "aborted_target_changed"
    for seen in calls.values():
        assert seen == [], seen
    assert cfg.production_live_pinned() is False


def test_live_flag_off_mid_run_aborts_before_next_write(client, tmp_path, monkeypatch):
    _live_env(monkeypatch)

    def flip_on_second(asin: str) -> OfferIn:
        if asin == ASIN_B:
            monkeypatch.setenv("EBAY_LIVE_UPLOAD_ENABLED", "false")
        return _offer(asin)

    calls = _install_stubs(monkeypatch, fetch_hook=flip_on_second)
    _write_upload(tmp_path, monkeypatch, TWO_LINES)
    plan = _plan(client, "upload", file="upload_items.txt")

    response = _upload_live(client, plan)
    assert response.status_code == 200, response.text
    status = _wait_done(client)

    assert status["phase"] == "aborted_live_disabled"
    assert [row["state"] for row in status["rows"]] == ["published", "error"]
    assert "aborted_live_disabled" in status["rows"][1]["reason"]
    assert calls["stage"] == [ASIN_A]
    assert calls["publish"] == [ASIN_A]
    assert calls["fetch"] == [ASIN_A, ASIN_B]


def test_audit_append_failure_aborts_before_next_write(client, tmp_path, monkeypatch):
    _live_env(monkeypatch)
    calls = _install_stubs(monkeypatch)
    _write_upload(tmp_path, monkeypatch, TWO_LINES)
    plan = _plan(client, "upload", file="upload_items.txt")

    original = upload_items.append_live_audit
    seen = {"count": 0}

    def flaky(entry):
        seen["count"] += 1
        # Start, intent and both writes succeed; the first result append fails.
        if entry.get("event") == "result":
            raise OSError("audit disk full")
        return original(entry)

    monkeypatch.setattr(upload_items, "append_live_audit", flaky)

    response = _upload_live(client, plan)
    assert response.status_code == 200, response.text
    status = _wait_done(client)

    assert status["phase"] == "aborted_audit_failed"
    assert calls["stage"] == [ASIN_A]
    assert calls["publish"] == [ASIN_A]
    assert calls["fetch"] == [ASIN_A]
    lines = _audit_lines(tmp_path)
    assert [line for line in lines if line.get("event") == "start"]


def test_start_line_audit_failure_aborts_before_any_write(client, tmp_path, monkeypatch):
    _live_env(monkeypatch)
    calls = _install_stubs(monkeypatch)
    _write_upload(tmp_path, monkeypatch, TWO_LINES)
    plan = _plan(client, "upload", file="upload_items.txt")

    def broken(entry):
        raise OSError("audit unavailable")

    monkeypatch.setattr(upload_items, "append_live_audit", broken)

    response = _upload_live(client, plan)

    assert response.status_code == 500, response.text
    assert response.json()["code"] == "LIVE_AUDIT_FAILED"
    for seen in calls.values():
        assert seen == [], seen
    assert client.get("/api/upload-items/status").json()["running"] is False


def test_live_and_sandbox_runs_never_overlap(client, tmp_path, monkeypatch):
    _live_env(monkeypatch)
    entered = threading.Event()
    release = threading.Event()

    def blocking_fetch(asin: str) -> OfferIn:
        entered.set()
        assert release.wait(5), "test did not release the blocked fetch"
        return _offer(asin)

    _install_stubs(monkeypatch, fetch_hook=blocking_fetch)
    _write_upload(tmp_path, monkeypatch, FILE_A)
    plan = _plan(client, "upload", file="upload_items.txt")

    try:
        response = _upload_live(client, plan, confirm="LIVE 1")
        assert response.status_code == 200, response.text
        assert entered.wait(5)
        assert cfg.production_live_pinned() is True
        assert cfg.upload_sandbox_pinned() is False

        # A second run is refused even after the target is switched to sandbox.
        monkeypatch.setattr(cfg, "ebay_env", lambda: "sandbox")
        second = client.post(
            "/api/upload-items/start",
            json={"mode": "full", "file": "upload_items.txt"},
        )
        assert second.status_code == 409, second.text
        assert "already running" in second.text.lower()
    finally:
        release.set()

    status = _wait_done(client)
    assert status["run_id"] == response.json()["run_id"]
    assert cfg.production_live_pinned() is False
    assert cfg.upload_sandbox_pinned() is False


# --------------------------------------------------------- publish live run


def test_live_publish_skips_existing_and_rechecks_prepared_price(
    client, tmp_path, monkeypatch
):
    _live_env(monkeypatch)
    _seed_prepared(ASIN_A)
    _seed_prepared(ASIN_B)
    ebay_listing.save_listing_state(
        ASIN_B,
        {"status": "published", "offer_id": "OFF-OLD", "listing_id": "1100OLD", "price": 40.0},
    )
    calls = _install_stubs(monkeypatch)
    _install_http_stub(monkeypatch)
    plan = _plan(client, "publish", asins=[ASIN_A, ASIN_B])
    assert plan["n"] == 2

    response = client.post(
        "/api/prepared/publish",
        json={
            "asins": [ASIN_A, ASIN_B],
            "confirm": "LIVE 2",
            "batch_hash": plan["batch_hash"],
            "plan_nonce": plan["nonce"],
        },
    )
    assert response.status_code == 200, response.text
    status = _wait_done(client)

    by_asin = {row["asin"]: row for row in status["rows"]}
    assert by_asin[ASIN_A]["state"] == "published"
    assert by_asin[ASIN_B]["state"] == "skipped_existing"
    assert calls["stage"] == [ASIN_A]
    assert calls["publish"] == [ASIN_A]
    # Publish re-checks the prepared sale price, not a fresh suggestion.
    assert calls["evaluate"] == [(ASIN_A, "always", 50.0)]
    lines = _audit_lines(tmp_path)
    rows = {line["asin"]: line for line in lines if line.get("event") == "result"}
    assert rows[ASIN_A]["state"] == "published"
    assert rows[ASIN_B]["state"] == "skipped_existing"


def test_live_publish_margin_failure_writes_nothing(client, tmp_path, monkeypatch):
    _live_env(monkeypatch)
    _seed_prepared(ASIN_A)
    calls = _install_stubs(monkeypatch, evaluate_passed=False)
    plan = _plan(client, "publish", asins=[ASIN_A])

    response = client.post(
        "/api/prepared/publish",
        json={
            "asins": [ASIN_A],
            "confirm": "LIVE 1",
            "batch_hash": plan["batch_hash"],
            "plan_nonce": plan["nonce"],
        },
    )
    assert response.status_code == 200, response.text
    status = _wait_done(client)

    assert status["rows"][0]["state"] == "rejected"
    assert calls["stage"] == []
    assert calls["publish"] == []


def test_live_publish_variation_parent_writes_nothing(client, tmp_path, monkeypatch):
    _live_env(monkeypatch)
    _seed_prepared(ASIN_A)
    calls = _install_stubs(
        monkeypatch,
        # The requested ASIN is the hub, not one of the returned children.
        variation_hook=lambda asin: [_offer(ASIN_B)],
    )
    plan = _plan(client, "publish", asins=[ASIN_A])

    response = client.post(
        "/api/prepared/publish",
        json={
            "asins": [ASIN_A],
            "confirm": "LIVE 1",
            "batch_hash": plan["batch_hash"],
            "plan_nonce": plan["nonce"],
        },
    )
    assert response.status_code == 200, response.text
    status = _wait_done(client)

    assert status["rows"][0]["state"] == "rejected"
    assert "variation_parent" in status["rows"][0]["reason"]
    assert calls["stage"] == []
    assert calls["publish"] == []


# --------------------------------------------------------- preview / health


def test_preview_overview_and_health_expose_live_gate(client, tmp_path, monkeypatch):
    _live_env(monkeypatch)
    _write_upload(tmp_path, monkeypatch, TWO_LINES)

    preview = client.get(
        "/api/upload-items/preview", params={"file": "upload_items.txt"}
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["live_disabled"] is False
    assert body["live_enabled"] is True
    assert body["live_missing"] == []
    assert body["live_cap"] == 5

    overview = client.get("/api/prepared").json()
    assert overview["live_disabled"] is False
    assert overview["live_enabled"] is True
    assert overview["live_missing"] == []
    assert overview["live_cap"] == 5

    health = client.get("/api/health").json()
    assert health["ebay"]["live_upload_enabled"] is True
    assert health["ebay"]["live_upload_missing"] == []
    assert health["ebay"]["live_max_per_run"] == 5


def test_preview_reports_reason_when_flag_off(client, tmp_path, monkeypatch):
    _live_env(monkeypatch, flag=False)
    _write_upload(tmp_path, monkeypatch, TWO_LINES)

    body = client.get(
        "/api/upload-items/preview", params={"file": "upload_items.txt"}
    ).json()

    assert body["live_disabled"] is True
    assert body["live_enabled"] is False
    assert "EBAY_LIVE_UPLOAD_ENABLED" in body["live_missing"]
