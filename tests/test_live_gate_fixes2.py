"""Round-2 structural regression tests for the guarded live path.

Covers the three structural rules (S1 environment frozen during an eBay
operation, S2 final transport guard immediately before dispatch, S3 fail-closed
live gate) and the follow-up fixes 4-8.  Every test is local-only: Amazon,
evaluate, the draft generator and the eBay HTTP transport are fakes/spies.
"""

from __future__ import annotations

import json
import threading
import time
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

import dropship_desk.api as api_mod
import dropship_desk.upload_items as upload_items
from dropship_desk import config as cfg
from dropship_desk.ebay import account_setup
from dropship_desk.ebay import client as ebay_http
from dropship_desk.ebay import listing as ebay_listing
from dropship_desk.ebay import oauth as ebay_oauth
from dropship_desk.ebay import pictures
from tests.test_live_gate import (
    ASIN_A,
    ASIN_B,
    FILE_A,
    TWO_LINES,
    _live_env,
    _install_stubs,
    _plan,
    _wait_done,
    _write_upload,
)
from tests.test_live_gate_fixes import (
    _PriceTransport,
    _seed_candidate,
    _stub_stage_io,
)

GATE_KEYS = ("EBAY_LIVE_UPLOAD_ENABLED", "EBAY_AUTOMATION_ENABLED", "EBAY_ALLOW_LIST")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cfg, "DB_PATH", tmp_path / "dropship.sqlite3")
    monkeypatch.setattr(upload_items.ebay_oauth, "oauth_connected", lambda env=None: True)
    monkeypatch.setattr(api_mod, "UPLOAD_JOB", upload_items.UploadJobManager())
    upload_items.clear_live_nonces()
    cfg.clear_live_env_cache()
    yield TestClient(api_mod.create_app())
    upload_items.clear_live_nonces()
    cfg.clear_live_env_cache()
    cfg.pin_sandbox_for_upload(False)
    cfg.pin_production_for_live(False)


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


def _write_token(tmp_path, target_env: str, **over) -> None:
    record = {"refresh_token": "r", "access_token": "a", "env": target_env}
    record.update(over)
    (tmp_path / f"ebay_oauth_{target_env}.json").write_text(
        json.dumps(record), encoding="utf-8"
    )


# =========================================================== S1: ebay_operation


def test_ebay_operation_counter_and_captured_env():
    assert cfg.ebay_ops_in_flight() == 0
    assert cfg.ebay_operation_running() is False
    with cfg.ebay_operation("production") as captured:
        assert captured == "production"
        assert cfg.ebay_ops_in_flight() == 1
        assert cfg.ebay_operation_running() is True
        assert cfg.operation_env() == "production"
        with cfg.ebay_operation("sandbox"):
            assert cfg.ebay_ops_in_flight() == 2
            assert cfg.operation_env() == "sandbox"
        assert cfg.operation_env() == "production"
        assert cfg.ebay_ops_in_flight() == 1
    assert cfg.ebay_ops_in_flight() == 0
    assert cfg.ebay_operation_running() is False


def test_target_switch_returns_409_while_operation_running(client, monkeypatch):
    _live_env(monkeypatch)
    with cfg.ebay_operation("production"):
        response = client.post("/api/ebay/target", json={"env": "sandbox"})

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "EBAY_OPERATION_RUNNING"


def test_oauth_callback_returns_409_when_env_change_while_operation_running(
    client, monkeypatch
):
    _live_env(monkeypatch)
    monkeypatch.setattr(cfg, "ebay_target_ready", lambda env=None: True)
    with cfg.ebay_operation("production"):
        response = client.get(
            "/api/ebay/oauth/callback", params={"code": "x", "state": "sandbox"}
        )

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "EBAY_OPERATION_RUNNING"


def test_oauth_callback_is_allowed_when_it_does_not_change_env(client, monkeypatch):
    _live_env(monkeypatch)
    monkeypatch.setattr(cfg, "ebay_target_ready", lambda env=None: True)
    calls: list[str] = []
    monkeypatch.setattr(
        ebay_oauth, "exchange_code", lambda code, env=None: calls.append(code) or {}
    )
    with cfg.ebay_operation("production"):
        response = client.get(
            "/api/ebay/oauth/callback", params={"code": "x", "state": "production"}
        )

    assert response.status_code == 200, response.text
    assert calls == ["x"]


def test_account_setup_runs_inside_an_ebay_operation(monkeypatch):
    seen: list[bool] = []
    monkeypatch.setattr(account_setup, "ensure_business_policy_opt_in", lambda http=None: None)
    monkeypatch.setattr(
        account_setup,
        "ensure_inventory_location",
        lambda http=None: seen.append(cfg.ebay_operation_running()) or "loc",
    )
    monkeypatch.setattr(account_setup, "_first_policy_id", lambda *a, **k: "id")

    record = account_setup.ensure_seller_setup(http=lambda *a, **k: {}, env="production")

    assert seen == [True]
    assert record["merchant_location_key"] == "loc"
    assert cfg.ebay_ops_in_flight() == 0


def test_legacy_stage_endpoint_runs_inside_an_ebay_operation(
    client, tmp_path, monkeypatch
):
    _live_env(monkeypatch, env="sandbox")
    _write_token(tmp_path, "sandbox")
    seen: dict[str, bool] = {}

    def fake_stage(asin, draft_patch=None, **kwargs):
        seen["running"] = cfg.ebay_operation_running()
        return {"asin": asin}

    monkeypatch.setattr(ebay_listing, "stage_unpublished", fake_stage)

    response = client.post(f"/api/ebay/listings/{ASIN_A}/stage", json={})

    assert response.status_code == 200, response.text
    assert seen["running"] is True
    assert cfg.ebay_ops_in_flight() == 0


def test_target_switch_409_while_worker_operation_is_paused(client, tmp_path, monkeypatch):
    _live_env(monkeypatch)
    calls = _install_stubs(monkeypatch)
    started = threading.Event()
    release = threading.Event()

    def pausing_stage(asin, draft_patch=None, **kwargs):
        calls["stage"].append(asin)
        started.set()
        assert release.wait(10), "test did not release the paused stage"
        ebay_listing.save_listing_state(
            asin,
            {"status": "unpublished", "offer_id": f"OFF-{asin}", "price": 50.0},
            env="production",
        )
        return ebay_listing.public_listing(asin, env="production")

    monkeypatch.setattr(upload_items.ebay_listing, "stage_unpublished", pausing_stage)
    _write_upload(tmp_path, monkeypatch, FILE_A)
    plan = _plan(client, "upload", file="upload_items.txt")

    response = _start_upload(client, plan, confirm="LIVE 1")
    assert response.status_code == 200, response.text
    assert started.wait(10), "worker never reached the paused stage"

    conflict = client.post("/api/ebay/target", json={"env": "sandbox"})
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["code"] == "EBAY_OPERATION_RUNNING"

    release.set()
    status = _wait_done(client)

    assert status["rows"][0]["state"] == "published"
    prod = ebay_listing.load_listing_state(ASIN_A, env="production")
    sandbox = ebay_listing.load_listing_state(ASIN_A, env="sandbox")
    assert prod["status"] == "published"
    assert sandbox == {}
    assert cfg.ebay_ops_in_flight() == 0


def _pausing_http_client(started: threading.Event, release: threading.Event, on_post):
    class _Response:
        status_code = 200
        content = b"{}"
        text = "{}"

        def json(self):
            return {"access_token": "new", "expires_in": 3600, "refresh_token": "r"}

    class _Client:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc_info) -> bool:
            return False

        def post(self, *args, **kwargs):
            started.set()
            assert release.wait(10), "test did not release the paused OAuth request"
            on_post()
            return _Response()

    return _Client


def test_target_switch_409_while_oauth_operation_is_paused(client, tmp_path, monkeypatch):
    holder = {"env": "production"}
    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cfg, "ebay_env", lambda: holder["env"])
    for key in ("EBAY_PROD_APP_ID", "EBAY_PROD_CERT_ID", "EBAY_PROD_RUNAME"):
        monkeypatch.setenv(key, "x")
    started, release = threading.Event(), threading.Event()
    monkeypatch.setattr(
        ebay_oauth.httpx,
        "Client",
        _pausing_http_client(
            started, release, lambda: holder.update(env="sandbox")
        ),
    )
    errors: list[BaseException] = []

    def run_exchange() -> None:
        try:
            ebay_oauth.exchange_code("code")
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    thread = threading.Thread(target=run_exchange)
    thread.start()
    assert started.wait(10), "OAuth request never started"

    conflict = client.post("/api/ebay/target", json={"env": "sandbox"})
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["code"] == "EBAY_OPERATION_RUNNING"

    release.set()
    thread.join(timeout=10)
    assert not thread.is_alive()
    assert errors == []
    prod = json.loads((tmp_path / "ebay_oauth_production.json").read_text(encoding="utf-8"))
    assert prod["access_token"] == "new"
    assert prod["env"] == "production"
    assert not (tmp_path / "ebay_oauth_sandbox.json").exists()
    assert cfg.ebay_ops_in_flight() == 0


def test_target_switch_409_while_account_operation_is_paused(
    client, tmp_path, monkeypatch
):
    holder = {"env": "production"}
    monkeypatch.setattr(cfg, "ebay_env", lambda: holder["env"])
    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)
    started, release = threading.Event(), threading.Event()
    monkeypatch.setattr(account_setup, "ensure_business_policy_opt_in", lambda http=None: None)
    monkeypatch.setattr(account_setup, "ensure_inventory_location", lambda http=None: "loc")

    def pausing_policy(*args, **kwargs):
        started.set()
        assert release.wait(10), "test did not release the paused account setup"
        holder["env"] = "sandbox"
        return "id"

    monkeypatch.setattr(account_setup, "_first_policy_id", pausing_policy)
    errors: list[BaseException] = []

    def run_setup() -> None:
        try:
            account_setup.ensure_seller_setup(http=lambda *a, **k: {})
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    thread = threading.Thread(target=run_setup)
    thread.start()
    assert started.wait(10), "account setup never started"

    conflict = client.post("/api/ebay/target", json={"env": "sandbox"})
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["code"] == "EBAY_OPERATION_RUNNING"

    release.set()
    thread.join(timeout=10)
    assert not thread.is_alive()
    assert errors == []
    assert (tmp_path / "ebay_account_production.json").exists()
    assert not (tmp_path / "ebay_account_sandbox.json").exists()
    assert cfg.ebay_ops_in_flight() == 0


# ====================================================== S2: transport ordering


def test_client_request_checks_token_env_before_the_final_guard(monkeypatch):
    monkeypatch.setattr(cfg, "ebay_env", lambda: "sandbox")
    order: list[str] = []
    real_guard = ebay_http.ensure_write_target_allowed
    monkeypatch.setattr(
        ebay_http,
        "ensure_write_target_allowed",
        lambda url: order.append("guard") or real_guard(url),
    )
    monkeypatch.setattr(
        ebay_http.ebay_oauth,
        "access_token",
        lambda: order.append("token") or "tok",
    )
    monkeypatch.setattr(
        ebay_http.ebay_oauth,
        "ensure_token_env_matches",
        lambda url: order.append("token-env"),
    )

    class _Response:
        status_code = 200
        content = b"{}"
        text = "{}"

        def json(self):
            return {}

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

        def request(self, *args, **kwargs):
            order.append("dispatch")
            return _Response()

    monkeypatch.setattr(ebay_http.httpx, "Client", _Client)

    ebay_http.request("GET", "/sell/inventory/v1/offer")

    assert order == ["guard", "token", "token-env", "guard", "guard", "dispatch"]


def _install_recording_client(monkeypatch) -> dict[str, int]:
    state = {"constructed": 0, "dispatched": 0}

    class _Response:
        status_code = 200
        content = b"{}"
        text = "{}"

        def json(self):
            return {}

    class _Client:
        def __init__(self, *args, **kwargs):
            state["constructed"] += 1

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

        def request(self, *args, **kwargs):
            state["dispatched"] += 1
            return _Response()

        def post(self, *args, **kwargs):
            state["dispatched"] += 1
            return _Response()

    monkeypatch.setattr(ebay_http.httpx, "Client", _Client)
    monkeypatch.setattr(ebay_oauth.httpx, "Client", _Client)
    monkeypatch.setattr(pictures.httpx, "Client", _Client)
    return state


def test_flag_flip_during_token_read_blocks_dispatch(monkeypatch):
    for key in GATE_KEYS:
        monkeypatch.setenv(key, "true")
    monkeypatch.setenv("EBAY_ENV", "production")
    monkeypatch.setattr(cfg, "ebay_env", lambda: "production")
    cfg.clear_live_env_cache()
    cfg.pin_production_for_live(True)
    state = _install_recording_client(monkeypatch)

    def flipping_token():
        monkeypatch.setenv("EBAY_LIVE_UPLOAD_ENABLED", "false")
        cfg.clear_live_env_cache()
        return "tok"

    monkeypatch.setattr(ebay_http.ebay_oauth, "access_token", flipping_token)
    try:
        with pytest.raises(RuntimeError, match="LIVE_WRITE_BLOCKED"):
            ebay_http.request("PUT", "/sell/inventory/v1/inventory_item/DD-X")
    finally:
        cfg.pin_production_for_live(False)
        cfg.clear_live_env_cache()

    assert state == {"constructed": 0, "dispatched": 0}


def test_target_flip_during_token_read_blocks_dispatch(monkeypatch):
    for key in GATE_KEYS:
        monkeypatch.setenv(key, "true")
    holder = {"env": "production"}
    monkeypatch.setenv("EBAY_ENV", "production")
    monkeypatch.setattr(cfg, "ebay_env", lambda: holder["env"])
    cfg.clear_live_env_cache()
    cfg.pin_production_for_live(True)
    state = _install_recording_client(monkeypatch)

    def flipping_token():
        holder["env"] = "sandbox"
        return "tok"

    monkeypatch.setattr(ebay_http.ebay_oauth, "access_token", flipping_token)
    try:
        with pytest.raises(RuntimeError, match="token env mismatch"):
            ebay_http.request("PUT", "/sell/inventory/v1/inventory_item/DD-X")
    finally:
        cfg.pin_production_for_live(False)
        cfg.clear_live_env_cache()

    assert state == {"constructed": 0, "dispatched": 0}


# ========================================================= S3: fail closed gate


def _gate_file(tmp_path, monkeypatch, text: str):
    path = tmp_path / ".env"
    path.write_text(text, encoding="utf-8")
    monkeypatch.setattr(cfg, "ENV_FILE", path, raising=False)
    cfg.clear_live_env_cache()
    return path


def _all_gate_env(monkeypatch, flag=True, automation=True, allow_list=True):
    monkeypatch.setenv("EBAY_LIVE_UPLOAD_ENABLED", "true" if flag else "false")
    monkeypatch.setenv("EBAY_AUTOMATION_ENABLED", "true" if automation else "false")
    monkeypatch.setenv("EBAY_ALLOW_LIST", "true" if allow_list else "false")


def _full_gate_file(flag="true", automation="true", allow_list="true") -> str:
    return (
        f"EBAY_LIVE_UPLOAD_ENABLED={flag}\n"
        f"EBAY_AUTOMATION_ENABLED={automation}\n"
        f"EBAY_ALLOW_LIST={allow_list}\n"
    )


def test_gate_without_any_env_file_uses_process_env(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "ENV_FILE", tmp_path / "missing.env", raising=False)
    _all_gate_env(monkeypatch)
    cfg.clear_live_env_cache()

    assert cfg.ebay_live_upload_enabled() is True
    assert cfg.ebay_automation_enabled() is True
    assert cfg.ebay_allow_list() is True


def test_gate_combines_file_and_process_env(tmp_path, monkeypatch):
    _gate_file(tmp_path, monkeypatch, _full_gate_file())
    _all_gate_env(monkeypatch, automation=False)

    assert cfg.ebay_live_upload_enabled() is True
    assert cfg.ebay_automation_enabled() is False
    assert cfg.ebay_allow_list() is True


def test_gate_comment_out_key_fails_closed(tmp_path, monkeypatch):
    _gate_file(
        tmp_path,
        monkeypatch,
        "# EBAY_LIVE_UPLOAD_ENABLED=true\n"
        "EBAY_AUTOMATION_ENABLED=true\n"
        "EBAY_ALLOW_LIST=true\n",
    )
    _all_gate_env(monkeypatch)

    assert cfg.ebay_live_upload_enabled() is False


def test_gate_missing_key_fails_closed(tmp_path, monkeypatch):
    _gate_file(
        tmp_path,
        monkeypatch,
        "EBAY_AUTOMATION_ENABLED=true\nEBAY_ALLOW_LIST=true\n",
    )
    _all_gate_env(monkeypatch)

    assert cfg.ebay_live_upload_enabled() is False


def test_gate_empty_file_fails_closed(tmp_path, monkeypatch):
    _gate_file(tmp_path, monkeypatch, "")
    _all_gate_env(monkeypatch)

    assert cfg.ebay_live_upload_enabled() is False


def test_gate_unterminated_quote_fails_closed(tmp_path, monkeypatch):
    _gate_file(
        tmp_path,
        monkeypatch,
        'EBAY_LIVE_UPLOAD_ENABLED="true\n'
        "EBAY_AUTOMATION_ENABLED=true\n"
        "EBAY_ALLOW_LIST=true\n",
    )
    _all_gate_env(monkeypatch)

    assert cfg.ebay_live_upload_enabled() is False


def test_gate_unreadable_file_fails_closed(tmp_path, monkeypatch):
    class _Denied:
        def __init__(self, path):
            self._path = path

        def is_file(self):
            return True

        def read_text(self, *args, **kwargs):
            raise PermissionError("denied")

        def __fspath__(self):
            return str(self._path)

        def __str__(self):
            return str(self._path)

    target = tmp_path / ".env"
    target.write_text(_full_gate_file(), encoding="utf-8")
    monkeypatch.setattr(cfg, "ENV_FILE", _Denied(target), raising=False)
    _all_gate_env(monkeypatch)
    cfg.clear_live_env_cache()

    assert cfg.ebay_live_upload_enabled() is False
    assert cfg.ebay_automation_enabled() is False
    assert cfg.ebay_allow_list() is False


def test_gate_unlinked_file_after_it_existed_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "LIVE_ENV_CACHE_SEC", 0.0)
    path = _gate_file(tmp_path, monkeypatch, _full_gate_file())
    _all_gate_env(monkeypatch)

    assert cfg.ebay_live_upload_enabled() is True
    path.unlink()

    assert cfg.ebay_live_upload_enabled() is False
    assert cfg.ebay_automation_enabled() is False
    assert cfg.ebay_allow_list() is False


def test_fail_closed_gate_blocks_live_write(tmp_path, monkeypatch):
    _gate_file(tmp_path, monkeypatch, "# all keys commented out\n")
    _all_gate_env(monkeypatch)
    monkeypatch.setenv("EBAY_ENV", "production")
    monkeypatch.setattr(cfg, "ebay_env", lambda: "production")
    cfg.pin_production_for_live(True)
    try:
        with pytest.raises(RuntimeError, match="LIVE_WRITE_BLOCKED"):
            cfg.ensure_write_target_allowed(
                "https://api.ebay.com/sell/inventory/v1/inventory_item/DD-X"
            )
    finally:
        cfg.pin_production_for_live(False)


# ==================================================== fix 4: test isolation


def test_conftest_uses_a_nonexistent_env_file():
    assert cfg.ENV_FILE.name != ".env", cfg.ENV_FILE
    assert not cfg.ENV_FILE.is_file(), cfg.ENV_FILE


# ============================================================ fix 5: nonces


@pytest.mark.parametrize("mode", ["upload", "publish"])
def test_changed_batch_burns_the_nonce_even_on_rejection(
    client, tmp_path, monkeypatch, mode
):
    _live_env(monkeypatch)
    _seed_candidate(ASIN_A)
    _seed_candidate(ASIN_B)
    calls = _install_stubs(monkeypatch)
    if mode == "upload":
        _write_upload(tmp_path, monkeypatch, TWO_LINES)
        plan = _plan(client, "upload", file="upload_items.txt")
        _write_upload(tmp_path, monkeypatch, FILE_A)
        changed = _start_upload(client, plan, confirm="LIVE 1")
        _write_upload(tmp_path, monkeypatch, TWO_LINES)
        retry = _start_upload(client, plan)
    else:
        plan = _plan(client, "publish", asins=[ASIN_A, ASIN_B])
        changed = _start_publish(client, plan, [ASIN_A])
        retry = _start_publish(client, plan, [ASIN_A, ASIN_B])

    assert changed.status_code == 409, changed.text
    assert changed.json()["code"] == "LIVE_CONFIRM_MISMATCH"
    assert retry.status_code == 409, retry.text
    assert retry.json()["code"] == "LIVE_CONFIRM_MISMATCH"
    assert calls["stage"] == []


@pytest.mark.parametrize("mode", ["upload", "publish"])
def test_n_mismatch_burns_the_nonce(client, tmp_path, monkeypatch, mode):
    _live_env(monkeypatch)
    _seed_candidate(ASIN_A)
    _seed_candidate(ASIN_B)
    _install_stubs(monkeypatch)
    if mode == "upload":
        _write_upload(tmp_path, monkeypatch, TWO_LINES)
        plan = _plan(client, "upload", file="upload_items.txt")
        first = _start_upload(client, plan, confirm="LIVE 1")
        second = _start_upload(client, plan)
    else:
        plan = _plan(client, "publish", asins=[ASIN_A, ASIN_B])
        first = _start_publish(client, plan, [ASIN_A, ASIN_B], confirm="LIVE 1")
        second = _start_publish(client, plan, [ASIN_A, ASIN_B])

    assert first.status_code == 409, first.text
    assert second.status_code == 409, second.text
    assert second.json()["code"] == "LIVE_CONFIRM_MISMATCH"


def test_nonce_store_is_capped_at_32():
    upload_items.clear_live_nonces()
    nonces = [
        upload_items.issue_live_nonce(
            mode="publish", env="production", batch_hash=f"h{i}", n=1
        )
        for i in range(33)
    ]

    with pytest.raises(upload_items.LiveConfirmMismatch):
        upload_items.validate_live_nonce(
            nonces[0], mode="publish", env="production", batch_hash="h0", n=1
        )
    upload_items.validate_live_nonce(
        nonces[-1], mode="publish", env="production", batch_hash="h32", n=1
    )
    assert len(upload_items._live_nonces) <= 32


# ============================================================ fix 6: prices


def test_canonical_price_rounds_half_up_to_two_decimals():
    assert ebay_listing.canonical_price(50.004) == 50.0
    assert ebay_listing.canonical_price(49.995) == 50.0
    assert ebay_listing.canonical_price(50.005) == 50.01
    assert ebay_listing.canonical_price(Decimal("49.994")) == 49.99


@pytest.mark.parametrize("expected", [50.004, 49.995])
def test_stage_binds_a_canonical_price(client, monkeypatch, expected):
    _seed_candidate(ASIN_A, price=50.0)
    transport = _PriceTransport()
    _stub_stage_io(monkeypatch)

    staged = ebay_listing.stage_unpublished(
        ASIN_A, expected_price=expected, http=transport
    )

    offer_body = next(
        body
        for method, path, body in transport.bodies
        if method == "POST" and path.endswith("/offer")
    )
    assert offer_body["pricingSummary"]["price"]["value"] == "50.00"
    assert staged["price"] == 50.0
    assert ebay_listing.load_listing_state(ASIN_A)["price"] == 50.0


def test_stage_rejects_beyond_the_005_boundary(client, monkeypatch):
    _seed_candidate(ASIN_A, price=50.0)
    transport = _PriceTransport()
    _stub_stage_io(monkeypatch)

    with pytest.raises(RuntimeError, match="PRICE_BINDING"):
        ebay_listing.stage_unpublished(
            ASIN_A, expected_price=50.005, http=transport
        )

    assert transport.bodies == []


# ====================================================== fix 7: explicit token


def test_explicit_token_still_requires_a_matching_url_env(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cfg, "ebay_env", lambda: "production")
    _write_token(tmp_path, "production", env="sandbox")
    state = _install_recording_client(monkeypatch)

    with pytest.raises(RuntimeError, match="token env mismatch"):
        ebay_http.request(
            "PUT", "/sell/inventory/v1/inventory_item/DD-X", token="explicit"
        )

    assert state == {"constructed": 0, "dispatched": 0}


def test_token_record_without_env_is_rejected_under_live_pin(
    tmp_path, monkeypatch
):
    for key in GATE_KEYS:
        monkeypatch.setenv(key, "true")
    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cfg, "ebay_env", lambda: "production")
    cfg.clear_live_env_cache()
    record = {"refresh_token": "r", "access_token": "a"}
    (tmp_path / "ebay_oauth_production.json").write_text(
        json.dumps(record), encoding="utf-8"
    )
    state = _install_recording_client(monkeypatch)
    cfg.pin_production_for_live(True)
    try:
        with pytest.raises(RuntimeError, match="token env"):
            ebay_http.request(
                "PUT", "/sell/inventory/v1/inventory_item/DD-X", token="explicit"
            )
    finally:
        cfg.pin_production_for_live(False)
        cfg.clear_live_env_cache()

    assert state == {"constructed": 0, "dispatched": 0}


# ================================================= fix 8: image/access token


def test_access_token_env_check(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cfg, "ebay_env", lambda: "production")
    _write_token(tmp_path, "production", env="sandbox")

    with pytest.raises(RuntimeError, match="token env mismatch"):
        ebay_oauth.access_token()


def test_access_token_record_without_env_under_live_pin(tmp_path, monkeypatch):
    for key in GATE_KEYS:
        monkeypatch.setenv(key, "true")
    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cfg, "ebay_env", lambda: "production")
    cfg.clear_live_env_cache()
    (tmp_path / "ebay_oauth_production.json").write_text(
        json.dumps(
            {
                "refresh_token": "r",
                "access_token": "a",
                "expires_at": "2999-01-01T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    cfg.pin_production_for_live(True)
    try:
        with pytest.raises(RuntimeError, match="token env"):
            ebay_oauth.access_token()
    finally:
        cfg.pin_production_for_live(False)
        cfg.clear_live_env_cache()


def _picture_file(tmp_path):
    path = tmp_path / "picture.jpg"
    path.write_bytes(b"\xff\xd8\xff\xe0fakejpeg")
    return path


def test_picture_upload_final_guard_is_last_before_dispatch(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "ebay_env", lambda: "sandbox")
    order: list[str] = []
    monkeypatch.setattr(
        pictures.ebay_http,
        "trading_endpoint",
        lambda: order.append("endpoint") or "https://api.sandbox.ebay.com/ws/api.dll",
    )
    monkeypatch.setattr(
        pictures.ebay_oauth,
        "access_token",
        lambda: order.append("token") or "tok",
    )
    monkeypatch.setattr(
        pictures.ebay_oauth,
        "ensure_token_env_matches",
        lambda url: order.append("token-env"),
    )
    monkeypatch.setattr(
        pictures.ebay_http,
        "ensure_write_target_allowed",
        lambda url: order.append("guard"),
    )

    class _Response:
        status_code = 200
        text = (
            '<UploadSiteHostedPicturesResponse '
            'xmlns="urn:ebay:apis:eBLBaseComponents">'
            "<FullURL>https://i.ebayimg.com/x.jpg</FullURL>"
            "</UploadSiteHostedPicturesResponse>"
        )

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

        def post(self, *args, **kwargs):
            order.append("dispatch")
            return _Response()

    monkeypatch.setattr(pictures.httpx, "Client", _Client)

    url = pictures._upload_one(_picture_file(tmp_path))

    assert url == "https://i.ebayimg.com/x.jpg"
    assert order == ["endpoint", "token", "token-env", "guard", "guard", "dispatch"]


def test_picture_upload_flag_flip_during_token_read_blocks_dispatch(
    tmp_path, monkeypatch
):
    for key in GATE_KEYS:
        monkeypatch.setenv(key, "true")
    monkeypatch.setenv("EBAY_ENV", "production")
    monkeypatch.setattr(cfg, "ebay_env", lambda: "production")
    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)
    cfg.clear_live_env_cache()
    _write_token(tmp_path, "production", expires_at="2999-01-01T00:00:00+00:00")
    state = _install_recording_client(monkeypatch)
    cfg.pin_production_for_live(True)

    def flipping_token():
        monkeypatch.setenv("EBAY_LIVE_UPLOAD_ENABLED", "false")
        cfg.clear_live_env_cache()
        return "tok"

    monkeypatch.setattr(pictures.ebay_oauth, "access_token", flipping_token)
    try:
        with pytest.raises(RuntimeError, match="LIVE_WRITE_BLOCKED"):
            pictures._upload_one(_picture_file(tmp_path))
    finally:
        cfg.pin_production_for_live(False)
        cfg.clear_live_env_cache()

    assert state == {"constructed": 0, "dispatched": 0}


def test_picture_upload_target_flip_during_token_read_blocks_dispatch(
    tmp_path, monkeypatch
):
    for key in GATE_KEYS:
        monkeypatch.setenv(key, "true")
    holder = {"env": "production"}
    monkeypatch.setenv("EBAY_ENV", "production")
    monkeypatch.setattr(cfg, "ebay_env", lambda: holder["env"])
    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)
    cfg.clear_live_env_cache()
    _write_token(tmp_path, "production", expires_at="2999-01-01T00:00:00+00:00")
    state = _install_recording_client(monkeypatch)
    cfg.pin_production_for_live(True)

    def flipping_token():
        holder["env"] = "sandbox"
        return "tok"

    monkeypatch.setattr(pictures.ebay_oauth, "access_token", flipping_token)
    try:
        with pytest.raises(RuntimeError, match="token env mismatch"):
            pictures._upload_one(_picture_file(tmp_path))
    finally:
        cfg.pin_production_for_live(False)
        cfg.clear_live_env_cache()

    assert state == {"constructed": 0, "dispatched": 0}


# ============================================== fix 9: published row reason


def test_published_then_target_changed_keeps_ids_and_reason(
    client, tmp_path, monkeypatch
):
    _live_env(monkeypatch)
    _seed_candidate(ASIN_A, price=50.0)
    holder = {"env": "production"}
    monkeypatch.setattr(cfg, "ebay_env", lambda: holder["env"])
    calls = _install_stubs(monkeypatch)

    def stage(asin, draft_patch=None, **kwargs):
        calls["stage"].append(asin)
        ebay_listing.save_listing_state(
            asin,
            {"status": "unpublished", "offer_id": f"OFF-{asin}", "price": 50.0},
            env="production",
        )
        return ebay_listing.public_listing(asin, env="production")

    def publish(asin):
        calls["publish"].append(asin)
        holder["env"] = "sandbox"
        ebay_listing.save_listing_state(
            asin,
            {
                "status": "published",
                "offer_id": f"OFF-{asin}",
                "listing_id": f"1100{asin}",
                "price": 50.0,
            },
            env="production",
        )
        return ebay_listing.public_listing(asin, env="production")

    monkeypatch.setattr(upload_items.ebay_listing, "stage_unpublished", stage)
    monkeypatch.setattr(upload_items.ebay_listing, "publish_offer", publish)
    _write_upload(tmp_path, monkeypatch, FILE_A)
    plan = _plan(client, "upload", file="upload_items.txt")

    response = _start_upload(client, plan, confirm="LIVE 1")
    assert response.status_code == 200, response.text
    status = _wait_done(client)

    row = status["rows"][0]
    assert row["state"] == "error"
    assert row["reason"] == "published in production; target changed after response"
    assert row["offer_id"] == f"OFF-{ASIN_A}"
    assert row["listing_id"] == f"1100{ASIN_A}"
    assert row["item_url"].endswith(f"1100{ASIN_A}")


@pytest.mark.parametrize("endpoint", ["stage", "publish"])
def test_legacy_endpoints_capture_env_once_at_entry(
    client, tmp_path, monkeypatch, endpoint
):
    """A target flip after the first env read must not reach production."""
    _live_env(monkeypatch, env="sandbox")
    _write_token(tmp_path, "sandbox")
    reads = {"n": 0}
    real = cfg.ebay_env

    def flipping():
        reads["n"] += 1
        return real() if reads["n"] == 1 else "production"

    monkeypatch.setattr(cfg, "ebay_env", flipping)
    seen: dict[str, str] = {}

    def fake(asin, *args, **kwargs):
        seen["env"] = cfg.operation_env()
        return {"asin": asin}

    monkeypatch.setattr(
        ebay_listing,
        "stage_unpublished" if endpoint == "stage" else "publish_offer",
        fake,
    )

    response = client.post(f"/api/ebay/listings/{ASIN_A}/{endpoint}", json={})

    assert response.status_code == 200, response.text
    assert seen["env"] == "sandbox"
    assert cfg.ebay_ops_in_flight() == 0


def test_dotenv_with_non_utf8_bytes_closes_gates_without_raising(monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_bytes("NOTE=Gr\xfc\xdfe\nEBAY_AUTOMATION_ENABLED=true\n".encode("cp1252"))
    monkeypatch.setattr(cfg, "ENV_FILE", env)
    cfg.clear_live_env_cache()
    monkeypatch.setenv("EBAY_AUTOMATION_ENABLED", "true")

    assert cfg.ebay_automation_enabled() is False


def test_dotenv_with_odd_quote_in_comment_keeps_gates_open(monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "SHOP_NOTE='x' # don't\nEBAY_AUTOMATION_ENABLED=true\n", encoding="utf-8"
    )
    monkeypatch.setattr(cfg, "ENV_FILE", env)
    cfg.clear_live_env_cache()
    monkeypatch.setenv("EBAY_AUTOMATION_ENABLED", "true")

    assert cfg.ebay_automation_enabled() is True


def test_every_httpx_client_block_rechecks_the_gate_before_dispatch():
    """Client construction/TLS setup can take time: guard again once inside."""
    import re
    from pathlib import Path

    root = Path(ebay_http.__file__).parent
    found = 0
    for name in ("client.py", "pictures.py", "oauth.py"):
        lines = (root / name).read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            if re.match(r"\s*with httpx\.Client\(.*\) as client:\s*$", line):
                found += 1
                assert "ensure_write_target_allowed" in lines[i + 1], (name, i + 1)
    assert found == 5
