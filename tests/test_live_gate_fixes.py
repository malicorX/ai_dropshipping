"""Regression tests for the reviewer findings on the guarded live path.

Every test here is local-only.  Amazon/evaluate/draft and the eBay transport are
fakes; no test creates a real HTTP client that can reach the network.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import dropship_desk.api as api_mod
import dropship_desk.upload_items as upload_items
from dropship_desk import config as cfg
from dropship_desk.ebay import client as ebay_http
from dropship_desk.ebay import listing as ebay_listing
from dropship_desk.ebay import oauth as ebay_oauth
from dropship_desk.models import OfferIn
from tests.test_live_gate import (
    ASIN_A,
    ASIN_B,
    TWO_LINES,
    _audit_lines,
    _install_stubs,
    _live_env,
    _seed_prepared,
    _wait_done,
    _write_upload,
)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cfg, "DB_PATH", tmp_path / "dropship.sqlite3")
    monkeypatch.setattr(upload_items.ebay_oauth, "oauth_connected", lambda env=None: True)
    monkeypatch.setattr(api_mod, "UPLOAD_JOB", upload_items.UploadJobManager())
    getattr(upload_items, "clear_live_nonces", lambda: None)()
    getattr(cfg, "clear_live_env_cache", lambda: None)()
    yield TestClient(api_mod.create_app())
    getattr(upload_items, "clear_live_nonces", lambda: None)()
    getattr(cfg, "clear_live_env_cache", lambda: None)()


def _plan(client: TestClient, mode: str, **extra) -> dict:
    response = client.post("/api/live/plan", json={"mode": mode, **extra})
    assert response.status_code == 200, response.text
    return response.json()


def _start_upload(client: TestClient, plan: dict, **over):
    body = {
        "mode": "full",
        "file": "upload_items.txt",
        "confirm": "LIVE 2",
        "batch_hash": plan["batch_hash"],
        "plan_nonce": plan.get("nonce", ""),
        **over,
    }
    return client.post("/api/upload-items/start", json=body)


def _start_publish(client: TestClient, plan: dict, asins: list[str], **over):
    body = {
        "asins": asins,
        "confirm": f"LIVE {len(asins)}",
        "batch_hash": plan["batch_hash"],
        "plan_nonce": plan.get("nonce", ""),
        **over,
    }
    return client.post("/api/prepared/publish", json=body)


def _seed_candidate(asin: str, *, price: float = 50.0) -> None:
    _seed_prepared(asin, price=price)


# ---------------------------------------------------- 1. legacy endpoints


@pytest.mark.parametrize("endpoint", ["stage", "publish"])
@pytest.mark.parametrize("confirm_live", [True, False])
def test_legacy_single_listing_endpoints_are_403_in_production(
    client, tmp_path, monkeypatch, endpoint, confirm_live
):
    _live_env(monkeypatch)
    calls = _install_stubs(monkeypatch)
    (tmp_path / "ebay_oauth_production.json").write_text(
        json.dumps({"refresh_token": "r", "access_token": "a", "env": "production"}),
        encoding="utf-8",
    )

    response = client.post(
        f"/api/ebay/listings/{ASIN_A}/{endpoint}",
        json={"confirm_live": confirm_live},
    )

    assert response.status_code == 403, response.text
    assert response.json()["code"] == "LIVE_UPLOAD_DISABLED"
    assert "Prepared" in response.json()["detail"]
    for seen in calls.values():
        assert seen == [], seen


def test_legacy_sandbox_stage_still_reaches_listing(client, tmp_path, monkeypatch):
    _live_env(monkeypatch, env="sandbox")
    calls = _install_stubs(monkeypatch)
    _seed_candidate(ASIN_A)
    (tmp_path / "ebay_oauth_sandbox.json").write_text(
        json.dumps({"refresh_token": "r", "access_token": "a", "env": "sandbox"}),
        encoding="utf-8",
    )

    response = client.post(f"/api/ebay/listings/{ASIN_A}/stage", json={})

    assert response.status_code == 200, response.text
    assert calls["stage"] == [ASIN_A]


# ---------------------------------------------------- 2. price binding


class _PriceTransport:
    """Minimal REST fake for stage_unpublished; records every body."""

    def __init__(self) -> None:
        self.bodies: list[tuple] = []

    def __call__(self, method, path, *, json_body=None, params=None, **kwargs):
        self.bodies.append((method, path, json_body))
        if method == "GET" and path.endswith("/offer"):
            return {"offers": []}
        if method == "POST" and path.endswith("/offer"):
            return {"offerId": "OFFER-1"}
        return {}


def _stub_stage_io(monkeypatch) -> None:
    from dropship_desk.ebay import account_setup, pictures, taxonomy

    monkeypatch.setattr(
        account_setup,
        "ensure_seller_setup",
        lambda http=None: {
            "merchant_location_key": "loc",
            "payment_policy_id": "pay",
            "return_policy_id": "ret",
            "fulfillment_policy_id": "ful",
        },
    )
    monkeypatch.setattr(
        taxonomy, "suggest_category", lambda title, http=None: {"category_id": "1", "tree_id": "0"}
    )
    monkeypatch.setattr(taxonomy, "aspects_for_category", lambda cid, tid, http=None: {})
    monkeypatch.setattr(taxonomy, "brand_mpn_fields", lambda aspects: ("Markenlos", "Nicht zutreffend"))
    monkeypatch.setattr(
        pictures, "collect_image_urls", lambda asin, draft: ["https://i.ebayimg.com/00/s/x.jpg"]
    )


def test_stage_unpublished_refuses_price_that_differs_from_candidate(
    client, tmp_path, monkeypatch
):
    _seed_candidate(ASIN_A, price=50.0)
    transport = _PriceTransport()
    _stub_stage_io(monkeypatch)

    with pytest.raises(RuntimeError, match="PRICE_BINDING"):
        ebay_listing.stage_unpublished(ASIN_A, expected_price=55.0, http=transport)

    assert transport.bodies == []
    prod = ebay_listing.load_listing_state(ASIN_A, env="production")
    assert prod == {}


def test_stage_unpublished_sends_and_records_the_expected_price(
    client, tmp_path, monkeypatch
):
    _seed_candidate(ASIN_A, price=50.0)
    transport = _PriceTransport()
    _stub_stage_io(monkeypatch)

    staged = ebay_listing.stage_unpublished(ASIN_A, expected_price=50.0, http=transport)

    offer_body = next(
        body
        for method, path, body in transport.bodies
        if method == "POST" and path.endswith("/offer")
    )
    assert offer_body["pricingSummary"]["price"]["value"] == "50.00"
    # The result is read back from the staged state, not from the evaluated price.
    ebay_listing.save_listing_state(
        ASIN_A, {**staged, "price": 49.99}, env="production"
    )
    reloaded = ebay_listing.load_listing_state(ASIN_A, env="production")
    assert reloaded["price"] == 49.99


def test_live_upload_worker_passes_expected_price_to_stage(client, tmp_path, monkeypatch):
    _live_env(monkeypatch)
    seen: dict[str, float] = {}
    calls = _install_stubs(monkeypatch)
    original_stage = ebay_listing.stage_unpublished

    def recording_stage(asin, draft_patch=None, *, expected_price=None, **kwargs):
        seen[asin] = expected_price
        return original_stage(
            asin, draft_patch=draft_patch, expected_price=expected_price, **kwargs
        )

    monkeypatch.setattr(upload_items.ebay_listing, "stage_unpublished", recording_stage)
    _write_upload(tmp_path, monkeypatch, TWO_LINES)
    plan = _plan(client, "upload", file="upload_items.txt")

    response = _start_upload(client, plan)
    assert response.status_code == 200, response.text
    status = _wait_done(client)

    assert [row["state"] for row in status["rows"]] == ["published", "published"]
    assert seen == {ASIN_A: 50.0, ASIN_B: 50.0}
    assert calls["stage"] == [ASIN_A, ASIN_B]


def test_live_publish_worker_passes_prepared_price_to_stage(client, tmp_path, monkeypatch):
    _live_env(monkeypatch)
    _seed_candidate(ASIN_A, price=42.0)
    seen: dict[str, float] = {}
    _install_stubs(monkeypatch)

    def recording_stage(asin, draft_patch=None, *, expected_price=None, **kwargs):
        seen[asin] = expected_price
        ebay_listing.save_listing_state(
            asin,
            {"status": "unpublished", "offer_id": f"OFF-{asin}", "price": expected_price},
            env="production",
        )
        return ebay_listing.public_listing(asin, env="production")

    monkeypatch.setattr(upload_items.ebay_listing, "stage_unpublished", recording_stage)
    plan = _plan(client, "publish", asins=[ASIN_A])

    response = _start_publish(client, plan, [ASIN_A])
    assert response.status_code == 200, response.text
    status = _wait_done(client)

    assert status["rows"][0]["state"] == "published"
    assert seen == {ASIN_A: 42.0}
    assert status["rows"][0]["price"] == 42.0


# ------------------------------------------- 3. gate re-check per call


def test_live_pin_rechecks_flag_automation_and_allow_list(monkeypatch):
    monkeypatch.setenv("EBAY_ENV", "production")
    monkeypatch.setenv("EBAY_LIVE_UPLOAD_ENABLED", "true")
    monkeypatch.setenv("EBAY_AUTOMATION_ENABLED", "true")
    monkeypatch.setenv("EBAY_ALLOW_LIST", "true")
    getattr(cfg, "clear_live_env_cache", lambda: None)()
    url = "https://api.ebay.com/sell/inventory/v1/inventory_item/DD-X"
    cfg.pin_production_for_live(True)
    try:
        cfg.ensure_write_target_allowed(url)

        monkeypatch.setenv("EBAY_AUTOMATION_ENABLED", "false")
        getattr(cfg, "clear_live_env_cache", lambda: None)()
        with pytest.raises(RuntimeError, match="LIVE_WRITE_BLOCKED"):
            cfg.ensure_write_target_allowed(url)

        monkeypatch.setenv("EBAY_AUTOMATION_ENABLED", "true")
        monkeypatch.setenv("EBAY_ALLOW_LIST", "false")
        getattr(cfg, "clear_live_env_cache", lambda: None)()
        with pytest.raises(RuntimeError, match="LIVE_WRITE_BLOCKED"):
            cfg.ensure_write_target_allowed(url)

        monkeypatch.setenv("EBAY_ALLOW_LIST", "true")
        monkeypatch.setenv("EBAY_LIVE_UPLOAD_ENABLED", "false")
        getattr(cfg, "clear_live_env_cache", lambda: None)()
        with pytest.raises(RuntimeError, match="LIVE_WRITE_BLOCKED"):
            cfg.ensure_write_target_allowed(url)
    finally:
        cfg.pin_production_for_live(False)


def test_live_flag_is_reread_from_env_file(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    # Every live-gate key must be present: a missing key now fails closed.
    env_file.write_text(
        "EBAY_LIVE_UPLOAD_ENABLED=false\n"
        "EBAY_AUTOMATION_ENABLED=true\n"
        "EBAY_ALLOW_LIST=true\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(cfg, "ENV_FILE", env_file, raising=False)
    monkeypatch.setenv("EBAY_ENV", "production")
    monkeypatch.setenv("EBAY_LIVE_UPLOAD_ENABLED", "true")
    monkeypatch.setenv("EBAY_AUTOMATION_ENABLED", "true")
    monkeypatch.setenv("EBAY_ALLOW_LIST", "true")
    getattr(cfg, "clear_live_env_cache", lambda: None)()
    url = "https://api.ebay.com/sell/inventory/v1/inventory_item/DD-X"
    cfg.pin_production_for_live(True)
    try:
        with pytest.raises(RuntimeError, match="LIVE_WRITE_BLOCKED"):
            cfg.ensure_write_target_allowed(url)

        env_file.write_text(
            "EBAY_LIVE_UPLOAD_ENABLED=true\n"
            "EBAY_AUTOMATION_ENABLED=true\n"
            "EBAY_ALLOW_LIST=true\n",
            encoding="utf-8",
        )
        getattr(cfg, "clear_live_env_cache", lambda: None)()
        cfg.ensure_write_target_allowed(url)
    finally:
        cfg.pin_production_for_live(False)
        getattr(cfg, "clear_live_env_cache", lambda: None)()


def test_conflicting_transport_pins_are_blocked(monkeypatch):
    monkeypatch.setenv("EBAY_ENV", "production")
    cfg.pin_sandbox_for_upload(True)
    cfg.pin_production_for_live(True)
    try:
        with pytest.raises(RuntimeError, match="conflicting transport pins"):
            cfg.ensure_write_target_allowed("https://api.ebay.com/sell/inventory/v1/offer")
    finally:
        cfg.pin_sandbox_for_upload(False)
        cfg.pin_production_for_live(False)


@pytest.mark.parametrize(
    "gate_var", ["EBAY_AUTOMATION_ENABLED", "EBAY_ALLOW_LIST"]
)
def test_live_flag_off_mid_run_after_row_one_blocks_row_two(
    client, tmp_path, monkeypatch, gate_var
):
    _live_env(monkeypatch)

    def flip(asin: str) -> OfferIn:
        if asin == ASIN_B:
            monkeypatch.setenv(gate_var, "false")
        return OfferIn(
            title=f"Product {asin}",
            amazon_total=20.0,
            asin=asin,
            url=f"https://www.amazon.de/dp/{asin}",
            in_stock=True,
            seller_country="CN",
            sold_by_amazon=False,
            image_urls=[f"https://images.example/{asin}.jpg"],
        )

    calls = _install_stubs(monkeypatch, fetch_hook=flip)
    _write_upload(tmp_path, monkeypatch, TWO_LINES)
    plan = _plan(client, "upload", file="upload_items.txt")

    response = _start_upload(client, plan)
    assert response.status_code == 200, response.text
    status = _wait_done(client)

    assert status["phase"] == "aborted_live_disabled"
    assert [row["state"] for row in status["rows"]] == ["published", "error"]
    assert calls["stage"] == [ASIN_A]


# -------------------------------------------- 4. transport validation


class _HttpRecorder:
    def __init__(self) -> None:
        self.constructed = 0
        self.calls: list[tuple] = []

    def client_class(self):
        recorder = self

        class _Response:
            status_code = 200
            content = b"{}"
            text = "{}"

            def json(self):
                return {"access_token": "new", "expires_in": 3600}

        class _Client:
            def __init__(self, *args, **kwargs) -> None:
                recorder.constructed += 1

            def __enter__(self):
                return self

            def __exit__(self, *exc_info) -> bool:
                return False

            def request(self, method, url, **kwargs):
                recorder.calls.append((method, url))
                return _Response()

            def post(self, *args, **kwargs):
                recorder.calls.append(("post", args))
                return _Response()

        return _Client


def test_client_request_rechecks_guard_after_token(monkeypatch):
    monkeypatch.setattr(cfg, "ebay_env", lambda: "sandbox")
    order: list[str] = []
    monkeypatch.setattr(
        ebay_http, "ensure_write_target_allowed", lambda url: order.append("guard")
    )
    monkeypatch.setattr(
        ebay_http.ebay_oauth,
        "access_token",
        lambda: (order.append("token"), "tok")[1],
    )
    recorder = _HttpRecorder()
    monkeypatch.setattr(ebay_http.httpx, "Client", recorder.client_class())

    ebay_http.request("GET", "/sell/inventory/v1/offer")

    assert order[:1] == ["guard"]
    assert "token" in order
    assert order[-1] == "guard"
    assert order.index("token") < len(order) - 1
    assert recorder.calls


def test_client_request_rejects_token_env_mismatch(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cfg, "ebay_env", lambda: "production")
    (tmp_path / "ebay_oauth_production.json").write_text(
        json.dumps(
            {
                "refresh_token": "r",
                "access_token": "a",
                "env": "sandbox",
                "expires_at": "2999-01-01T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    recorder = _HttpRecorder()
    monkeypatch.setattr(ebay_http.httpx, "Client", recorder.client_class())
    monkeypatch.setattr(ebay_http, "ensure_write_target_allowed", lambda url: None)

    with pytest.raises(RuntimeError, match="token env mismatch"):
        ebay_http.request("PUT", "/sell/inventory/v1/inventory_item/DD-X")

    assert recorder.constructed == 0


def test_client_request_rejects_host_env_flip_after_token(monkeypatch):
    holder = {"env": "sandbox"}
    monkeypatch.setattr(cfg, "ebay_env", lambda: holder["env"])
    monkeypatch.setattr(ebay_http, "ensure_write_target_allowed", lambda url: None)
    recorder = _HttpRecorder()
    monkeypatch.setattr(ebay_http.httpx, "Client", recorder.client_class())
    monkeypatch.setattr(
        ebay_http.ebay_oauth,
        "access_token",
        lambda: (holder.update(env="production"), "tok")[1],
    )

    with pytest.raises(RuntimeError, match="token env mismatch"):
        ebay_http.request("PUT", "/sell/inventory/v1/inventory_item/DD-X")

    assert recorder.constructed == 0


def test_oauth_guards_are_called_before_http(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cfg, "ebay_env", lambda: "production")
    monkeypatch.setenv("EBAY_PROD_APP_ID", "app")
    monkeypatch.setenv("EBAY_PROD_CERT_ID", "cert")
    monkeypatch.setenv("EBAY_PROD_RUNAME", "runame")
    calls: list[str] = []
    monkeypatch.setattr(
        ebay_oauth.config, "ensure_write_target_allowed", lambda url: calls.append(url)
    )
    recorder = _HttpRecorder()
    monkeypatch.setattr(ebay_oauth.httpx, "Client", recorder.client_class())
    ebay_oauth.clear_application_token_cache()

    ebay_oauth.exchange_code("code")
    ebay_oauth._refresh_access_token("refresh")
    ebay_oauth.application_token()

    assert len(calls) == 6  # early guard + re-check inside the client block
    assert recorder.constructed == 3


@pytest.mark.parametrize("path", ["refresh", "exchange"])
def test_oauth_saves_tokens_under_request_env_when_target_flips(
    tmp_path, monkeypatch, path
):
    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)
    holder = {"env": "production"}
    monkeypatch.setattr(cfg, "ebay_env", lambda: holder["env"])
    monkeypatch.setenv("EBAY_PROD_APP_ID", "app")
    monkeypatch.setenv("EBAY_PROD_CERT_ID", "cert")
    monkeypatch.setenv("EBAY_PROD_RUNAME", "runame")
    (tmp_path / "ebay_oauth_production.json").write_text(
        json.dumps({"refresh_token": "old", "access_token": "old", "env": "production"}),
        encoding="utf-8",
    )

    class _Response:
        status_code = 200
        content = b"{}"
        text = "{}"

        def json(self):
            return {"access_token": "new", "expires_in": 3600}

    class _Client:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc_info) -> bool:
            return False

        def post(self, *args, **kwargs):
            holder["env"] = "sandbox"
            return _Response()

    monkeypatch.setattr(ebay_oauth.httpx, "Client", _Client)

    if path == "refresh":
        ebay_oauth._refresh_access_token("old")
    else:
        ebay_oauth.exchange_code("code")

    prod = json.loads((tmp_path / "ebay_oauth_production.json").read_text(encoding="utf-8"))
    assert prod["access_token"] == "new"
    assert prod["env"] == "production"
    assert not (tmp_path / "ebay_oauth_sandbox.json").exists()


# ------------------------------------- 5. state saved against run env


def test_listing_state_env_argument_keeps_targets_isolated(client, monkeypatch):
    _seed_candidate(ASIN_A, price=50.0)

    ebay_listing.save_listing_state(
        ASIN_A, {"status": "published", "listing_id": "1100PROD"}, env="production"
    )
    ebay_listing.save_listing_state(
        ASIN_A, {"status": "unpublished", "offer_id": "OFF-SBX"}, env="sandbox"
    )

    prod = ebay_listing.load_listing_state(ASIN_A, env="production")
    sandbox = ebay_listing.load_listing_state(ASIN_A, env="sandbox")
    assert prod["status"] == "published"
    assert sandbox["status"] == "unpublished"


def test_target_flip_during_publish_response_saves_production_state(
    client, tmp_path, monkeypatch
):
    _live_env(monkeypatch)
    _seed_candidate(ASIN_A, price=50.0)
    holder = {"env": "production"}
    monkeypatch.setattr(cfg, "ebay_env", lambda: holder["env"])
    calls = _install_stubs(monkeypatch)

    def flipping_stage(asin, draft_patch=None, **kwargs):
        calls["stage"].append(asin)
        ebay_listing.save_listing_state(
            asin,
            {"status": "unpublished", "offer_id": f"OFF-{asin}", "price": 50.0},
        )
        return ebay_listing.public_listing(asin)

    def flipping_publish(asin):
        calls["publish"].append(asin)
        # The target changes while the publish response is in flight.
        holder["env"] = "sandbox"
        # Default env inside the run must still be the run's start env.
        ebay_listing.save_listing_state(
            asin,
            {
                "status": "published",
                "offer_id": f"OFF-{asin}",
                "listing_id": f"1100{asin}",
                "price": 50.0,
            },
        )
        return ebay_listing.public_listing(asin, env="production")

    monkeypatch.setattr(upload_items.ebay_listing, "stage_unpublished", flipping_stage)
    monkeypatch.setattr(upload_items.ebay_listing, "publish_offer", flipping_publish)
    _write_upload(tmp_path, monkeypatch, "https://www.amazon.de/dp/B0LIVE0001\n")
    plan = _plan(client, "upload", file="upload_items.txt")

    response = _start_upload(client, plan, confirm="LIVE 1")
    assert response.status_code == 200, response.text
    status = _wait_done(client)

    prod = ebay_listing.load_listing_state(ASIN_A, env="production")
    sandbox = ebay_listing.load_listing_state(ASIN_A, env="sandbox")
    assert prod["status"] == "published"
    assert sandbox == {}
    assert status["phase"] == "aborted_target_changed"
    assert status["rows"][0]["state"] == "error"
    assert "target changed after response" in status["rows"][0]["reason"]


def test_publish_offer_saves_request_env_when_target_flips(client, monkeypatch):
    _seed_candidate(ASIN_A, price=50.0)
    holder = {"env": "production"}
    monkeypatch.setattr(cfg, "ebay_env", lambda: holder["env"])
    ebay_listing.save_listing_state(
        ASIN_A, {"status": "unpublished", "offer_id": "OFF-1", "price": 50.0}, env="production"
    )

    def fake_http(method, path, **kwargs):
        holder["env"] = "sandbox"
        return {"listingId": "1100FLIP"}

    published = ebay_listing.publish_offer(ASIN_A, http=fake_http, env="production")

    assert published["status"] == "published"
    prod = ebay_listing.load_listing_state(ASIN_A, env="production")
    assert prod["status"] == "published"
    assert prod["listing_id"] == "1100FLIP"
    assert ebay_listing.load_listing_state(ASIN_A, env="sandbox") == {}


# ------------------------------------------- 6. audit intent/result


def test_live_audit_writes_intent_before_first_ebay_call_and_result_after(
    client, tmp_path, monkeypatch
):
    _live_env(monkeypatch)
    order: list[str] = []
    calls = _install_stubs(monkeypatch)
    original_stage = ebay_listing.stage_unpublished

    def recording_stage(asin, draft_patch=None, *, expected_price=None, **kwargs):
        order.append(f"stage:{asin}")
        return original_stage(asin, draft_patch=draft_patch, expected_price=expected_price, **kwargs)

    monkeypatch.setattr(upload_items.ebay_listing, "stage_unpublished", recording_stage)
    original_append = upload_items.append_live_audit

    def recording_append(entry):
        order.append(f"audit:{entry.get('event')}:{entry.get('asin', '')}")
        return original_append(entry)

    monkeypatch.setattr(upload_items, "append_live_audit", recording_append)
    _write_upload(tmp_path, monkeypatch, "https://www.amazon.de/dp/B0LIVE0001\n")
    plan = _plan(client, "upload", file="upload_items.txt")

    response = _start_upload(client, plan, confirm="LIVE 1")
    assert response.status_code == 200, response.text
    status = _wait_done(client)

    intent_at = order.index(f"audit:intent:{ASIN_A}")
    stage_at = order.index(f"stage:{ASIN_A}")
    result_at = order.index(f"audit:result:{ASIN_A}")
    assert intent_at < stage_at < result_at

    lines = _audit_lines(tmp_path)
    intent = next(line for line in lines if line.get("event") == "intent")
    result = next(line for line in lines if line.get("event") == "result")
    assert intent["run_id"] == status["run_id"]
    assert intent["asin"] == ASIN_A
    assert intent["sku"] == f"DD-{ASIN_A}"
    assert intent["price"] == 50.0
    assert intent["mode"] == "full"
    assert result["state"] == "published"
    assert result["price"] == 50.0
    assert not [line for line in lines if line.get("event") == "row"]


def test_intent_audit_failure_blocks_ebay_calls_and_aborts(client, tmp_path, monkeypatch):
    _live_env(monkeypatch)
    calls = _install_stubs(monkeypatch)
    _write_upload(tmp_path, monkeypatch, TWO_LINES)
    plan = _plan(client, "upload", file="upload_items.txt")

    original = upload_items.append_live_audit

    def flaky(entry):
        if entry.get("event") == "intent":
            raise OSError("audit disk full")
        return original(entry)

    monkeypatch.setattr(upload_items, "append_live_audit", flaky)

    response = _start_upload(client, plan)
    assert response.status_code == 200, response.text
    status = _wait_done(client)

    assert status["phase"] == "aborted_audit_failed"
    assert calls["stage"] == []
    assert calls["publish"] == []
    assert "LIVE_AUDIT_FAILED" in status["rows"][0]["reason"]


# ------------------------------------------------ 7. plan nonce


def test_plan_returns_nonce_and_start_requires_it(client, tmp_path, monkeypatch):
    _live_env(monkeypatch)
    _install_stubs(monkeypatch)
    _write_upload(tmp_path, monkeypatch, TWO_LINES)
    plan = _plan(client, "upload", file="upload_items.txt")

    assert isinstance(plan.get("nonce"), str) and len(plan["nonce"]) >= 16

    missing = _start_upload(client, plan, plan_nonce="")
    assert missing.status_code == 409, missing.text
    assert missing.json()["code"] == "LIVE_CONFIRM_MISMATCH"

    ok = _start_upload(client, plan)
    assert ok.status_code == 200, ok.text
    _wait_done(client)


def test_plan_nonce_is_single_use_after_success(client, tmp_path, monkeypatch):
    _live_env(monkeypatch)
    calls = _install_stubs(monkeypatch)
    _write_upload(tmp_path, monkeypatch, TWO_LINES)
    plan = _plan(client, "upload", file="upload_items.txt")

    first = _start_upload(client, plan)
    assert first.status_code == 200, first.text
    _wait_done(client)

    replay = _start_upload(client, plan)
    assert replay.status_code == 409, replay.text
    assert replay.json()["code"] == "LIVE_CONFIRM_MISMATCH"
    assert calls["stage"] == [ASIN_A, ASIN_B]


def test_plan_nonce_expires(client, tmp_path, monkeypatch):
    _live_env(monkeypatch)
    calls = _install_stubs(monkeypatch)
    _write_upload(tmp_path, monkeypatch, TWO_LINES)
    plan = _plan(client, "upload", file="upload_items.txt")
    monkeypatch.setattr(upload_items, "LIVE_NONCE_TTL_SEC", 0.0, raising=False)

    response = _start_upload(client, plan)

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "LIVE_CONFIRM_MISMATCH"
    assert calls["stage"] == []


def test_plan_nonce_for_another_batch_is_rejected(client, tmp_path, monkeypatch):
    _live_env(monkeypatch)
    _seed_candidate(ASIN_A)
    _seed_candidate(ASIN_B)
    calls = _install_stubs(monkeypatch)
    _write_upload(tmp_path, monkeypatch, TWO_LINES)
    upload_plan = _plan(client, "upload", file="upload_items.txt")
    publish_plan = _plan(client, "publish", asins=[ASIN_A])

    response = _start_publish(
        client, publish_plan, [ASIN_A], batch_hash=publish_plan["batch_hash"]
    )
    assert response.status_code == 200, response.text
    _wait_done(client)

    # Reuse the consumed publish nonce with the upload hash -> mismatch.
    replay = _start_upload(client, upload_plan, plan_nonce=publish_plan["nonce"])
    assert replay.status_code == 409, replay.text
    assert replay.json()["code"] == "LIVE_CONFIRM_MISMATCH"


# --------------------------- 9. parametrized upload/publish coverage


def _setup_mode(client, tmp_path, monkeypatch, mode: str):
    _live_env(monkeypatch)
    calls = _install_stubs(monkeypatch)
    if mode == "upload":
        _write_upload(tmp_path, monkeypatch, TWO_LINES)
        plan = _plan(client, "upload", file="upload_items.txt")
    else:
        _seed_candidate(ASIN_A)
        _seed_candidate(ASIN_B)
        plan = _plan(client, "publish", asins=[ASIN_A, ASIN_B])
    return calls, plan


def _start_mode(client, mode: str, plan: dict, **over):
    if mode == "upload":
        return _start_upload(client, plan, **over)
    return _start_publish(client, plan, [ASIN_A, ASIN_B], **over)


@pytest.mark.parametrize("mode", ["upload", "publish"])
@pytest.mark.parametrize("confirm", [None, "LIVE 1", "live 2", "LIVE 2 ", ""])
def test_confirm_mismatch_is_409_in_both_modes(
    client, tmp_path, monkeypatch, mode, confirm
):
    calls, plan = _setup_mode(client, tmp_path, monkeypatch, mode)

    response = _start_mode(client, mode, plan, confirm=confirm)

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "LIVE_CONFIRM_MISMATCH"
    assert calls["stage"] == []


@pytest.mark.parametrize("mode", ["upload", "publish"])
@pytest.mark.parametrize("bad_hash", [None, "", "0" * 64])
def test_hash_mismatch_is_409_in_both_modes(
    client, tmp_path, monkeypatch, mode, bad_hash
):
    calls, plan = _setup_mode(client, tmp_path, monkeypatch, mode)

    response = _start_mode(client, mode, plan, batch_hash=bad_hash)

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "LIVE_CONFIRM_MISMATCH"
    assert calls["stage"] == []


@pytest.mark.parametrize("mode", ["upload", "publish"])
@pytest.mark.parametrize(("cap", "expected"), [(2, 200), (1, 400)])
def test_cap_off_by_one_in_both_modes(
    client, tmp_path, monkeypatch, mode, cap, expected
):
    _live_env(monkeypatch, cap=cap)
    calls = _install_stubs(monkeypatch)
    if mode == "upload":
        _write_upload(tmp_path, monkeypatch, TWO_LINES)
        plan = _plan(client, "upload", file="upload_items.txt")
    else:
        _seed_candidate(ASIN_A)
        _seed_candidate(ASIN_B)
        plan = _plan(client, "publish", asins=[ASIN_A, ASIN_B])

    response = _start_mode(client, mode, plan)

    assert response.status_code == expected, response.text
    if expected == 400:
        assert response.json()["code"] == "LIVE_CAP_EXCEEDED"
        assert calls["stage"] == []
    else:
        _wait_done(client)


@pytest.mark.parametrize("mode", ["upload", "publish"])
@pytest.mark.parametrize("broken", ["flag", "automation", "allow_list", "account"])
def test_each_gate_closes_both_modes(client, tmp_path, monkeypatch, mode, broken):
    calls, plan = _setup_mode(client, tmp_path, monkeypatch, mode)
    if broken == "flag":
        monkeypatch.setenv("EBAY_LIVE_UPLOAD_ENABLED", "false")
    elif broken == "automation":
        monkeypatch.setenv("EBAY_AUTOMATION_ENABLED", "false")
    elif broken == "allow_list":
        monkeypatch.setenv("EBAY_ALLOW_LIST", "false")
    else:
        monkeypatch.setattr(upload_items.ebay_oauth, "oauth_connected", lambda env=None: False)
    getattr(cfg, "clear_live_env_cache", lambda: None)()

    response = _start_mode(client, mode, plan)

    assert response.status_code == 403, response.text
    assert response.json()["code"] == "LIVE_UPLOAD_DISABLED"
    assert calls["stage"] == []


@pytest.mark.parametrize("mode", ["upload", "publish"])
def test_start_audit_failure_aborts_both_modes(
    client, tmp_path, monkeypatch, mode
):
    calls, plan = _setup_mode(client, tmp_path, monkeypatch, mode)

    def broken(entry):
        raise OSError("audit unavailable")

    monkeypatch.setattr(upload_items, "append_live_audit", broken)

    response = _start_mode(client, mode, plan)

    assert response.status_code == 500, response.text
    assert response.json()["code"] == "LIVE_AUDIT_FAILED"
    assert calls["stage"] == []


def test_hash_binds_mode_and_env(client, tmp_path, monkeypatch):
    _live_env(monkeypatch)
    _seed_candidate(ASIN_A)
    _write_upload(tmp_path, monkeypatch, "https://www.amazon.de/dp/B0LIVE0001\n")
    upload = _plan(client, "upload", file="upload_items.txt")
    publish = _plan(client, "publish", asins=[ASIN_A])

    assert upload["batch_hash"] != publish["batch_hash"]
    monkeypatch.setattr(cfg, "ebay_env", lambda: "sandbox")
    sandbox_publish = _plan(client, "publish", asins=[ASIN_A])
    assert sandbox_publish["batch_hash"] != publish["batch_hash"]


def test_publish_plan_dedupes_duplicate_asins(client, monkeypatch):
    _live_env(monkeypatch)
    _seed_candidate(ASIN_A)
    _seed_candidate(ASIN_B)

    plan = _plan(client, "publish", asins=[ASIN_A, ASIN_A, ASIN_B, ASIN_A])

    assert plan["n"] == 2
    assert [item["asin"] for item in plan["items"]] == [ASIN_A, ASIN_B]


def test_upload_plan_counts_only_queued_rows(client, tmp_path, monkeypatch):
    _live_env(monkeypatch)
    _write_upload(
        tmp_path,
        monkeypatch,
        "https://www.amazon.de/dp/B0LIVE0001\n"
        "https://www.amazon.de/dp/B0LIVE0001\n"
        "not an asin\n"
        "https://www.amazon.de/dp/B0LIVE0002\n",
    )

    plan = _plan(client, "upload", file="upload_items.txt")

    assert plan["n"] == 2
    assert [item["asin"] for item in plan["items"]] == [ASIN_A, ASIN_B]


def test_publish_price_binding_records_staged_price(client, tmp_path, monkeypatch):
    _live_env(monkeypatch)
    _seed_candidate(ASIN_A, price=50.0)
    _install_stubs(monkeypatch)

    def staged_price(asin, draft_patch=None, *, expected_price=None, **kwargs):
        ebay_listing.save_listing_state(
            asin,
            {"status": "unpublished", "offer_id": f"OFF-{asin}", "price": 49.95},
            env="production",
        )
        return ebay_listing.public_listing(asin, env="production")

    monkeypatch.setattr(upload_items.ebay_listing, "stage_unpublished", staged_price)
    plan = _plan(client, "publish", asins=[ASIN_A])

    response = _start_publish(client, plan, [ASIN_A])
    assert response.status_code == 200, response.text
    status = _wait_done(client)

    assert status["rows"][0]["state"] == "published"
    assert status["rows"][0]["price"] == 49.95
    result = next(
        line for line in _audit_lines(tmp_path) if line.get("event") == "result"
    )
    assert result["price"] == 49.95
