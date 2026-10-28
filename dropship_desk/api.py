"""FastAPI application for Dropship Desk."""

from __future__ import annotations

import asyncio
import logging
import sys
import webbrowser
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from dropship_desk import __version__, config
from dropship_desk.amazon.product import fetch_variation_offers
from dropship_desk.ebay import listing as ebay_listing
from dropship_desk.ebay import oauth as ebay_oauth
from dropship_desk.ebay.client import EbayApiError
from dropship_desk.db import (
    apply_stored_ebay_target,
    ensure_margin_policy,
    get_listing_draft,
    get_margin_settings,
    init_db,
    list_candidates,
    prune_rejected,
    set_ebay_target,
    set_margin_settings,
)
from dropship_desk.enrich import ENRICH_JOB, enrich_missing
from dropship_desk.listing_generate import ListingGenerateError, generate_draft
from dropship_desk.ollama_client import ollama_reachable
from dropship_desk.product_media import (
    image_content_type,
    product_dir,
    resolve_image_file,
)
from dropship_desk.reprice import reprice_candidates
from dropship_desk.evaluate_service import run_evaluate
from dropship_desk.prepared import overview as prepared_overview
from dropship_desk.variation_expand import persist_variation_offers
from dropship_desk.find_job import FIND_JOB
from dropship_desk.listing_template import (
    get_listing_shop_settings,
    set_listing_shop_settings,
)
from dropship_desk.models import (
    DiscoverySettings,
    EvaluateRequest,
    EvaluateResponse,
    MarginSettings,
    OpenExternalRequest,
    SettingsIn,
    SettingsOut,
)
from dropship_desk.safety import check_ebay_sell
from dropship_desk.upload_items import (
    UPLOAD_JOB,
    InvalidUploadFile,
    LiveAuditError,
    LiveCapExceeded,
    LiveConfirmMismatch,
    LiveUploadDisabled,
    NotSignedIn,
    UploadAlreadyRunning,
    UploadFileMissing,
    live_gate_missing,
    list_upload_files,
    mark_row_listed,
    plan_live_batch,
    published_listing_state,
    read_upload_file,
    resolve_upload_file,
)

_ALLOWED_OPEN_HOSTS = frozenset(
    {
        "www.amazon.de",
        "amazon.de",
        "www.ebay.de",
        "ebay.de",
        "www.ebay.com",
        "ebay.com",
        "auth.ebay.com",
        "auth.sandbox.ebay.com",
        "www.sandbox.ebay.com",
        "sandbox.ebay.com",
    }
)


def _ebay_health() -> dict:
    sell = check_ebay_sell()
    missing = live_gate_missing()
    return {
        **ebay_oauth.public_status(),
        "sell_allowed": sell.ok,
        "sell_block_reason": "" if sell.ok else sell.reason,
        "live_upload_enabled": config.ebay_live_upload_enabled(),
        "live_max_per_run": config.ebay_live_max_per_run(),
        "live_upload_missing": missing,
        "live_upload_ready": not missing,
    }


def _invalid_upload_file(exc: InvalidUploadFile) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={"code": "INVALID_UPLOAD_FILE", "detail": str(exc)},
    )


class _SkipNoisyAccess(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return "/api/health" not in msg and "/api/find/status" not in msg


def _benign_disconnect(exc: BaseException | None) -> bool:
    if isinstance(exc, ConnectionResetError):
        return True
    return getattr(exc, "winerror", None) == 10054


def _loop_exception_handler(loop: asyncio.AbstractEventLoop, context: dict) -> None:
    if _benign_disconnect(context.get("exception")):
        return
    loop.default_exception_handler(context)


def create_app() -> FastAPI:
    init_db()
    ensure_margin_policy()
    apply_stored_ebay_target()
    app = FastAPI(title="Dropship Desk", version=__version__)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:8770",
            "http://127.0.0.1:8770",
            "https://localhost:8770",
            "https://127.0.0.1:8770",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    async def _quiet_webview_disconnects() -> None:
        loop = asyncio.get_running_loop()
        loop.set_exception_handler(_loop_exception_handler)
        logging.getLogger("uvicorn.access").addFilter(_SkipNoisyAccess())

    @app.get("/api/health")
    def health() -> dict:
        return {
            "status": "ok",
            "version": __version__,
            "frozen": config.IS_FROZEN,
            "automation": config.automation_snapshot(),
            "ollama_base_url": config.OLLAMA_BASE_URL,
            "ollama_model": config.OLLAMA_MODEL,
            "ollama_reachable": ollama_reachable(),
            "data_dir": str(config.DATA_DIR),
            "find_running": FIND_JOB.status()["running"],
            "ebay": _ebay_health(),
        }

    @app.get("/api/settings", response_model=SettingsOut)
    def read_settings() -> SettingsOut:
        return SettingsOut(
            margin=get_margin_settings(),
            listing_shop=get_listing_shop_settings(),
            ollama_base_url=config.OLLAMA_BASE_URL,
            ollama_model=config.OLLAMA_MODEL,
        )

    @app.put("/api/settings", response_model=SettingsOut)
    def write_settings(body: SettingsIn) -> SettingsOut:
        if body.margin is not None:
            set_margin_settings(body.margin)
        if body.listing_shop is not None:
            set_listing_shop_settings(body.listing_shop)
        return SettingsOut(
            margin=get_margin_settings(),
            listing_shop=get_listing_shop_settings(),
            ollama_base_url=config.OLLAMA_BASE_URL,
            ollama_model=config.OLLAMA_MODEL,
        )

    @app.post("/api/ebay/target")
    def ebay_target_set(body: dict | None = None) -> dict:
        env = config.normalize_ebay_env(str((body or {}).get("env") or ""))
        if env == "production" and UPLOAD_JOB.status().get("running"):
            return JSONResponse(
                status_code=409,
                content={
                    "code": "UPLOAD_RUNNING",
                    "detail": (
                        "UPLOAD_RUNNING: an upload-from-file run is active; switching to "
                        "production is locked until it finishes (sandbox is allowed)"
                    ),
                },
            )
        if config.ebay_operation_running():
            # The eBay env is frozen while any seller/OAuth/account operation
            # is in flight; a real switch would split that operation across
            # two environments.  A redundant no-op request is harmless.
            if env != config.normalize_ebay_env(config.ebay_env()):
                return JSONResponse(
                    status_code=409,
                    content={
                        "code": "EBAY_OPERATION_RUNNING",
                        "detail": (
                            "EBAY_OPERATION_RUNNING: an eBay operation is in "
                            "flight; the target cannot change until it finishes"
                        ),
                    },
                )
        if env == "production" and not config.ebay_target_ready("production"):
            gaps = ", ".join(config.ebay_target_gaps("production")) or "production keys"
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Live eBay is missing {gaps} in .env. Create a Production RuName at "
                    "developer.ebay.com (Auth accepted URL "
                    f"https://127.0.0.1:{config.DEFAULT_API_PORT}/api/ebay/oauth/callback), "
                    "then restart."
                ),
            )
        set_ebay_target(env)
        return _ebay_health()

    @app.get("/api/ebay/status")
    def ebay_status() -> dict:
        return ebay_oauth.public_status()

    @app.post("/api/ebay/oauth/start")
    def ebay_oauth_start() -> dict:
        try:
            url = ebay_oauth.authorize_url()
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        webbrowser.open(url)
        return {"ok": True, "authorize_url": url, "env": config.ebay_env()}

    @app.get("/api/ebay/oauth/callback")
    def ebay_oauth_callback(
        code: str | None = None,
        error: str | None = None,
        state: str | None = None,
    ) -> HTMLResponse:
        if error:
            return HTMLResponse(
                f"<html><body><h1>eBay OAuth failed</h1><p>{error}</p>"
                "<p>You can close this tab.</p></body></html>",
                status_code=400,
            )
        if not code:
            raise HTTPException(status_code=400, detail="missing code")
        if state:
            callback_env = config.normalize_ebay_env(state)
            current_env = config.normalize_ebay_env(config.ebay_env())
            if callback_env == "production" and UPLOAD_JOB.status().get("running"):
                return JSONResponse(
                    status_code=409,
                    content={
                        "code": "UPLOAD_RUNNING",
                        "detail": (
                            "UPLOAD_RUNNING: an upload-from-file run is active; "
                            "switching to production is locked until it finishes "
                            "(sandbox is allowed)"
                        ),
                    },
                )
            if callback_env != current_env and config.ebay_operation_running():
                return JSONResponse(
                    status_code=409,
                    content={
                        "code": "EBAY_OPERATION_RUNNING",
                        "detail": (
                            "EBAY_OPERATION_RUNNING: an eBay operation is in "
                            "flight; the target cannot change until it finishes"
                        ),
                    },
                )
            if config.ebay_target_ready(callback_env):
                set_ebay_target(callback_env)
        try:
            ebay_oauth.exchange_code(code)
        except Exception as e:  # noqa: BLE001
            return HTMLResponse(
                f"<html><body><h1>Token exchange failed</h1><pre>{e}</pre></body></html>",
                status_code=502,
            )
        env = config.ebay_env()
        return HTMLResponse(
            "<html><body style='font-family:sans-serif;padding:2rem'>"
            f"<h1>eBay {env} connected</h1>"
            "<p>You can close this tab and return to Dropship Desk → Settings.</p>"
            "</body></html>"
        )

    def _require_ebay_sell(body: dict | None = None) -> None:
        op_env = config.operation_env()
        if not ebay_oauth.load_tokens().get("refresh_token"):
            label = "live eBay" if op_env == "production" else "sandbox eBay"
            raise HTTPException(
                status_code=400,
                detail=f"eBay is not connected — Settings → Connect {label}",
            )
        decision = check_ebay_sell()
        if not decision.ok:
            raise HTTPException(status_code=403, detail=decision.reason)
        if op_env == "production" and not (body or {}).get("confirm_live"):
            raise HTTPException(
                status_code=400,
                detail="Live eBay Send/Publish needs an explicit confirm in the app",
            )

    def _legacy_live_response() -> JSONResponse:
        """The old single-listing endpoints are closed in production.

        They write outside the guarded upload/publish plan (no server batch,
        no cap, no live audit), so production always points the operator at
        the Prepared tab / upload plan instead.  Sandbox is unchanged.
        """
        return JSONResponse(
            status_code=403,
            content={
                "code": "LIVE_UPLOAD_DISABLED",
                "detail": (
                    "LIVE_UPLOAD_DISABLED: single-listing stage/publish is "
                    "disabled in production — use the Prepared tab or the "
                    "guarded upload plan."
                ),
            },
        )

    @app.get("/api/ebay/listings/{asin}")
    def ebay_listing_get(asin: str) -> dict:
        return ebay_listing.public_listing(asin)

    @app.post("/api/ebay/listings/{asin}/stage")
    def ebay_listing_stage(asin: str, body: dict | None = None):
        try:
            with config.ebay_operation(config.ebay_env()) as op_env:
                if op_env == "production":
                    return _legacy_live_response()
                _require_ebay_sell(body)
                return ebay_listing.stage_unpublished(asin, body or None)
        except EbayApiError as e:
            sys.stderr.write(f"[ebay] stage failed: {e}\n")
            raise HTTPException(status_code=502, detail=str(e)) from e
        except RuntimeError as e:
            sys.stderr.write(f"[ebay] stage failed: {e}\n")
            raise HTTPException(status_code=400, detail=str(e)) from e

    @app.post("/api/ebay/listings/{asin}/publish")
    def ebay_listing_publish(asin: str, body: dict | None = None):
        try:
            with config.ebay_operation(config.ebay_env()) as op_env:
                if op_env == "production":
                    return _legacy_live_response()
                _require_ebay_sell(body)
                return ebay_listing.publish_offer(asin)
        except EbayApiError as e:
            sys.stderr.write(f"[ebay] publish failed: {e}\n")
            raise HTTPException(status_code=502, detail=str(e)) from e
        except RuntimeError as e:
            sys.stderr.write(f"[ebay] publish failed: {e}\n")
            raise HTTPException(status_code=400, detail=str(e)) from e

    @app.get("/api/candidates")
    def candidates(limit: int = 200, status: str | None = None) -> list[dict]:
        return list_candidates(limit=limit, status=status)

    @app.post("/api/candidates/prune-rejected")
    def candidates_prune(days: int = 7) -> dict:
        deleted = prune_rejected(older_than_days=max(1, days))
        return {"deleted": deleted, "older_than_days": days}

    @app.post("/api/candidates/reprice")
    def candidates_reprice(status: str | None = None) -> dict:
        """Recalculate eBay prices from stored Amazon totals using current margin settings."""
        return reprice_candidates(status=status or None)

    @app.post("/api/candidates/enrich-missing")
    def candidates_enrich_missing(limit: int = 20, status: str | None = "ready") -> dict:
        """Sync PDP enrich (tests / scripts). Prefer /start for UI progress."""
        return enrich_missing(limit=min(limit, 40), status=status or None, pause_sec=0)

    @app.post("/api/candidates/enrich-missing/start")
    def candidates_enrich_start(limit: int = 20, status: str | None = "ready") -> dict:
        try:
            return ENRICH_JOB.start(limit=min(limit, 40), status=status or None)
        except RuntimeError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e

    @app.get("/api/candidates/enrich-missing/status")
    def candidates_enrich_status() -> dict:
        return ENRICH_JOB.status()

    @app.post("/api/candidates/enrich-missing/stop")
    def candidates_enrich_stop() -> dict:
        return ENRICH_JOB.stop()

    @app.post("/api/live/plan")
    def live_plan(body: dict | None = None) -> dict:
        """Read-only batch plan: server n + hash + item preview, no eBay write."""
        payload = body or {}
        try:
            return plan_live_batch(
                mode=payload.get("mode") or "upload",
                file=payload.get("file"),
                asins=payload.get("asins"),
            )
        except InvalidUploadFile as e:
            return _invalid_upload_file(e)
        except UploadFileMissing as e:
            raise HTTPException(
                status_code=404, detail=f"UPLOAD_FILE_MISSING: {e.path}"
            ) from e
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @app.get("/api/upload-items/files")
    def upload_items_files() -> dict:
        """The selectable ``*.txt`` lists directly inside the upload folder."""
        return list_upload_files()

    @app.get("/api/upload-items/preview")
    def upload_items_preview(file: str | None = None) -> dict:
        env = config.ebay_env()
        try:
            path = resolve_upload_file(file)
            rows = read_upload_file(path)
        except InvalidUploadFile as e:
            return _invalid_upload_file(e)
        except UploadFileMissing as e:
            raise HTTPException(
                status_code=404, detail=f"UPLOAD_FILE_MISSING: {e.path}"
            ) from e
        # Local state files only: the preview never touches Amazon or eBay.
        for row in rows:
            if row.state != "queued":
                continue
            existing = published_listing_state(row.asin, env)
            if existing is not None:
                mark_row_listed(row, existing, row_state="already_listed")
        missing = live_gate_missing(env)
        return {
            "target_env": env,
            "live_disabled": env == "production" and bool(missing),
            "live_enabled": env == "production" and not missing,
            "live_missing": missing,
            "live_cap": config.ebay_live_max_per_run(),
            "path": str(path),
            "file": path.name,
            "rows": [row.to_dict() for row in rows],
        }

    @app.post("/api/upload-items/start")
    def upload_items_start(body: dict | None = None) -> dict:
        payload = body or {}
        mode = str(payload.get("mode") or "full").strip().lower()
        file_name = payload.get("file")
        try:
            return UPLOAD_JOB.start(
                mode=mode,
                file=file_name,
                confirm=payload.get("confirm"),
                batch_hash=payload.get("batch_hash"),
                plan_nonce=payload.get("plan_nonce"),
            )
        except LiveUploadDisabled as e:
            return JSONResponse(
                status_code=403,
                content={
                    "code": "LIVE_UPLOAD_DISABLED",
                    "detail": str(e),
                    "missing": e.missing,
                },
            )
        except LiveCapExceeded as e:
            return JSONResponse(
                status_code=400,
                content={
                    "code": "LIVE_CAP_EXCEEDED",
                    "detail": str(e),
                    "n": e.n,
                    "cap": e.cap,
                },
            )
        except LiveConfirmMismatch as e:
            return JSONResponse(
                status_code=409,
                content={"code": "LIVE_CONFIRM_MISMATCH", "detail": str(e)},
            )
        except LiveAuditError as e:
            return JSONResponse(
                status_code=500,
                content={"code": "LIVE_AUDIT_FAILED", "detail": str(e)},
            )
        except InvalidUploadFile as e:
            return _invalid_upload_file(e)
        except UploadAlreadyRunning as e:
            raise HTTPException(status_code=409, detail=str(e)) from e
        except NotSignedIn as e:
            raise HTTPException(status_code=409, detail=str(e)) from e
        except UploadFileMissing as e:
            raise HTTPException(
                status_code=404, detail=f"UPLOAD_FILE_MISSING: {e.path}"
            ) from e
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @app.get("/api/prepared")
    def prepared_items() -> dict:
        """Local overview of drafted items that are not live yet."""
        return prepared_overview()

    @app.post("/api/prepared/publish")
    def prepared_publish(body: dict | None = None) -> dict:
        payload = body or {}
        raw_asins = payload.get("asins")
        # Keep raw values: start_publish() is the validation trust boundary and
        # must be able to reject non-strings instead of stringifying them.
        asins = list(raw_asins) if isinstance(raw_asins, list) else []
        if not asins:
            raise HTTPException(status_code=400, detail="asins required (non-empty list)")
        try:
            return UPLOAD_JOB.start_publish(
                asins,
                confirm=payload.get("confirm"),
                batch_hash=payload.get("batch_hash"),
                plan_nonce=payload.get("plan_nonce"),
            )
        except LiveUploadDisabled as e:
            return JSONResponse(
                status_code=403,
                content={
                    "code": "LIVE_UPLOAD_DISABLED",
                    "detail": str(e),
                    "missing": e.missing,
                },
            )
        except LiveCapExceeded as e:
            return JSONResponse(
                status_code=400,
                content={
                    "code": "LIVE_CAP_EXCEEDED",
                    "detail": str(e),
                    "n": e.n,
                    "cap": e.cap,
                },
            )
        except LiveConfirmMismatch as e:
            return JSONResponse(
                status_code=409,
                content={"code": "LIVE_CONFIRM_MISMATCH", "detail": str(e)},
            )
        except LiveAuditError as e:
            return JSONResponse(
                status_code=500,
                content={"code": "LIVE_AUDIT_FAILED", "detail": str(e)},
            )
        except UploadAlreadyRunning as e:
            raise HTTPException(status_code=409, detail=str(e)) from e
        except NotSignedIn as e:
            raise HTTPException(status_code=409, detail=str(e)) from e
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @app.get("/api/upload-items/status")
    def upload_items_status() -> dict:
        return UPLOAD_JOB.status()

    @app.post("/api/upload-items/stop")
    def upload_items_stop() -> dict:
        return UPLOAD_JOB.stop()

    @app.post("/api/open-external")
    def open_external(body: OpenExternalRequest) -> dict:
        parsed = urlparse(body.url.strip())
        if parsed.scheme != "https" or parsed.hostname not in _ALLOWED_OPEN_HOSTS:
            raise HTTPException(status_code=400, detail="URL host not allowed")
        webbrowser.open(body.url.strip())
        return {"ok": True, "url": body.url.strip()}

    @app.post("/api/amazon/refresh")
    def amazon_refresh(body: dict) -> dict:
        """Fetch live PDP price; explode size/color children into their own ASINs."""
        asin = str(body.get("asin") or "").strip().upper()
        if len(asin) != 10:
            raise HTTPException(status_code=400, detail="asin required (10 chars)")
        ebay_price = body.get("ebay_price")
        try:
            offers = fetch_variation_offers(asin)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=str(e)) from e
        persist = "always"
        expanded = persist_variation_offers(asin, offers, persist=persist)
        results = expanded.results
        if not results:
            offer = offers[0]
            result = run_evaluate(
                EvaluateRequest(
                    asin_or_url=offer.asin,
                    offer=offer,
                    ebay_price=float(ebay_price) if ebay_price is not None else None,
                    save=True,
                ),
                persist="always",
            )
            results = [result]
        primary = next((r for r in results if r.passed), results[0])
        return {
            "offer": primary.offer.model_dump(),
            "evaluate": primary.model_dump(),
            "expanded": expanded.expanded,
            "children": [
                {
                    "asin": r.asin,
                    "title": r.offer.title,
                    "variation_label": r.offer.variation_label,
                    "amazon_total": r.offer.amazon_total,
                    "passed": r.passed,
                    "ebay_price": r.ebay_price,
                }
                for r in results
            ],
        }

    @app.post("/api/listing/generate")
    def listing_generate(body: dict) -> dict:
        """Create unique eBay copy via sparky2 Ollama (not a 1:1 Amazon clone)."""
        try:
            return generate_draft(
                asin=body.get("asin"),
                ebay_price=body.get("ebay_price"),
                amazon_total=body.get("amazon_total"),
                title=body.get("title"),
                force_refresh_images=bool(body.get("force_refresh_images", False)),
            )
        except ListingGenerateError as e:
            raise HTTPException(status_code=e.status_code, detail=e.detail) from e

    @app.get("/api/listing/{asin}")
    def listing_get(asin: str) -> dict:
        draft = get_listing_draft(asin)
        if not draft:
            raise HTTPException(status_code=404, detail="no draft")
        return {"asin": asin.upper(), "draft": draft}

    @app.get("/api/products/{asin}/images/{filename}")
    def product_image(asin: str, filename: str) -> FileResponse:
        path = resolve_image_file(asin, filename)
        if path is None:
            raise HTTPException(status_code=404, detail="image not found")
        return FileResponse(path, media_type=image_content_type(path))

    @app.get("/api/products/{asin}/listing_draft.html")
    def product_draft_html(asin: str) -> FileResponse:
        path = product_dir(asin) / "listing_draft.html"
        if not path.is_file():
            raise HTTPException(status_code=404, detail="draft html not found")
        return FileResponse(path, media_type="text/html; charset=utf-8")

    @app.get("/api/products/{asin}/listing_draft.json")
    def product_draft_json(asin: str) -> FileResponse:
        path = product_dir(asin) / "listing_draft.json"
        if not path.is_file():
            raise HTTPException(status_code=404, detail="draft json not found")
        return FileResponse(path, media_type="application/json")

    @app.post("/api/products/{asin}/open-draft")
    def open_product_draft(asin: str, request: Request) -> dict:
        """Open the saved listing_draft.html in the system browser."""
        asin = asin.strip().upper()
        path = product_dir(asin) / "listing_draft.html"
        if not path.is_file():
            raise HTTPException(
                status_code=404,
                detail="draft html not found — generate a listing first",
            )
        base = str(request.base_url).rstrip("/")
        url = f"{base}/api/products/{asin}/listing_draft.html"
        webbrowser.open(url)
        return {"ok": True, "url": url}

    @app.post("/api/evaluate", response_model=EvaluateResponse)
    def evaluate(body: EvaluateRequest) -> EvaluateResponse:
        if body.offer is None:
            raise HTTPException(
                status_code=400,
                detail="offer required (or use /api/amazon/refresh for live PDP fetch)",
            )
        try:
            return run_evaluate(body)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @app.post("/api/find/start")
    def find_start(body: DiscoverySettings) -> dict:
        try:
            return FIND_JOB.start(body)
        except RuntimeError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e

    @app.post("/api/find/stop")
    def find_stop() -> dict:
        FIND_JOB.stop()
        return FIND_JOB.status()

    @app.get("/api/find/status")
    def find_status() -> dict:
        return FIND_JOB.status()

    ui_dist = config.RUNTIME_ROOT / "ui" / "dist"
    index_html = ui_dist / "index.html"
    if index_html.is_file():
        assets = ui_dist / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/")
        def spa_index() -> FileResponse:
            return FileResponse(index_html)

        @app.get("/{full_path:path}")
        def spa_fallback(full_path: str) -> FileResponse:
            candidate = ui_dist / full_path
            if candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(index_html)

    return app
