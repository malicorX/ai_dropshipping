"""FastAPI application for Dropship Desk."""

from __future__ import annotations

import asyncio
import logging
import sys
import webbrowser
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from dropship_desk import __version__, config
from dropship_desk.amazon.product import fetch_product_offer
from dropship_desk.ebay import listing as ebay_listing
from dropship_desk.ebay import oauth as ebay_oauth
from dropship_desk.ebay.client import EbayApiError
from dropship_desk.db import (
    ensure_margin_policy,
    get_candidate_by_asin,
    get_listing_draft,
    get_margin_settings,
    init_db,
    list_candidates,
    patch_candidate_offer,
    prune_rejected,
    save_listing_draft,
    set_margin_settings,
)
from dropship_desk.enrich import ENRICH_JOB, enrich_missing
from dropship_desk.ollama_client import generate_listing_draft, ollama_reachable
from dropship_desk.product_media import (
    download_product_images,
    image_content_type,
    product_dir,
    resolve_image_file,
    save_draft_artifacts,
)
from dropship_desk.reprice import reprice_candidates
from dropship_desk.evaluate_service import run_evaluate
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
    return {
        **ebay_oauth.public_status(),
        "sell_allowed": sell.ok,
        "sell_block_reason": "" if sell.ok else sell.reason,
    }


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
    def ebay_oauth_callback(code: str | None = None, error: str | None = None) -> HTMLResponse:
        if error:
            return HTMLResponse(
                f"<html><body><h1>eBay OAuth failed</h1><p>{error}</p>"
                "<p>You can close this tab.</p></body></html>",
                status_code=400,
            )
        if not code:
            raise HTTPException(status_code=400, detail="missing code")
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

    def _require_ebay_sell() -> None:
        if not ebay_oauth.load_tokens().get("refresh_token"):
            raise HTTPException(
                status_code=400,
                detail="eBay is not connected — Settings → Connect eBay",
            )
        decision = check_ebay_sell()
        if not decision.ok:
            raise HTTPException(status_code=403, detail=decision.reason)

    @app.get("/api/ebay/listings/{asin}")
    def ebay_listing_get(asin: str) -> dict:
        return ebay_listing.public_listing(asin)

    @app.post("/api/ebay/listings/{asin}/stage")
    def ebay_listing_stage(asin: str, body: dict | None = None) -> dict:
        _require_ebay_sell()
        try:
            return ebay_listing.stage_unpublished(asin, body or None)
        except EbayApiError as e:
            sys.stderr.write(f"[ebay] stage failed: {e}\n")
            raise HTTPException(status_code=502, detail=str(e)) from e
        except RuntimeError as e:
            sys.stderr.write(f"[ebay] stage failed: {e}\n")
            raise HTTPException(status_code=400, detail=str(e)) from e

    @app.post("/api/ebay/listings/{asin}/publish")
    def ebay_listing_publish(asin: str) -> dict:
        _require_ebay_sell()
        try:
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

    @app.post("/api/open-external")
    def open_external(body: OpenExternalRequest) -> dict:
        parsed = urlparse(body.url.strip())
        if parsed.scheme != "https" or parsed.hostname not in _ALLOWED_OPEN_HOSTS:
            raise HTTPException(status_code=400, detail="URL host not allowed")
        webbrowser.open(body.url.strip())
        return {"ok": True, "url": body.url.strip()}

    @app.post("/api/amazon/refresh")
    def amazon_refresh(body: dict) -> dict:
        """Fetch live PDP price/stars for one ASIN and upsert candidate."""
        asin = str(body.get("asin") or "").strip().upper()
        if len(asin) != 10:
            raise HTTPException(status_code=400, detail="asin required (10 chars)")
        ebay_price = body.get("ebay_price")
        try:
            offer = fetch_product_offer(asin)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=str(e)) from e
        result = run_evaluate(
            EvaluateRequest(
                asin_or_url=asin,
                offer=offer,
                ebay_price=float(ebay_price) if ebay_price is not None else None,
                save=True,
            ),
            persist="always",
        )
        return {
            "offer": offer.model_dump(),
            "evaluate": result.model_dump(),
        }

    @app.post("/api/listing/generate")
    def listing_generate(body: dict) -> dict:
        """Create unique eBay copy via sparky2 Ollama (not a 1:1 Amazon clone)."""
        asin = str(body.get("asin") or "").strip().upper()
        if len(asin) != 10:
            raise HTTPException(status_code=400, detail="asin required (10 chars)")
        if not ollama_reachable():
            raise HTTPException(
                status_code=503,
                detail=f"Ollama unreachable at {config.OLLAMA_BASE_URL}",
            )

        row = get_candidate_by_asin(asin)
        ebay_price = body.get("ebay_price")
        amazon_title = str(body.get("title") or (row["title"] if row else "") or "")
        amazon_total = body.get("amazon_total")
        if amazon_total is None and row:
            amazon_total = row["amazon_total"]
        if ebay_price is None and row:
            ebay_price = row["ebay_price"]
        if amazon_total is None or ebay_price is None:
            raise HTTPException(status_code=400, detail="amazon_total and ebay_price required")

        image_urls: list[str] = []
        offer_data = (row or {}).get("offer") or {}
        image_urls = list(offer_data.get("image_urls") or [])
        refresh = bool(body.get("refresh_images", True))
        if refresh or not image_urls:
            try:
                offer = fetch_product_offer(asin)
                image_urls = offer.image_urls or image_urls
                amazon_title = offer.title or amazon_title
                amazon_total = offer.amazon_total
                run_evaluate(
                    EvaluateRequest(
                        asin_or_url=asin,
                        offer=offer,
                        ebay_price=float(ebay_price),
                        save=True,
                    ),
                    persist="always",
                )
            except Exception:  # noqa: BLE001
                # Keep going with whatever title/images we already have.
                pass

        force_imgs = bool(body.get("force_refresh_images", False))
        media = download_product_images(
            asin,
            image_urls,
            force=force_imgs,
        )
        patch_candidate_offer(
            asin,
            {
                "image_urls": media.get("source_urls") or image_urls,
                "local_images": media.get("local_images") or [],
            },
        )

        try:
            draft = generate_listing_draft(
                amazon_title=amazon_title,
                asin=asin,
                amazon_price=float(amazon_total),
                ebay_price=float(ebay_price),
                image_urls=image_urls,
            )
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"LLM generate failed: {e}") from e

        artifacts = save_draft_artifacts(asin, draft, media)
        draft["artifacts"] = artifacts
        draft["media"] = {
            "local_images": media.get("local_images") or [],
            "source_urls": media.get("source_urls") or [],
            "download_errors": media.get("errors") or [],
        }

        if row or get_candidate_by_asin(asin):
            save_listing_draft(asin, draft)
        return {"draft": draft, "asin": asin, "media": media, "artifacts": artifacts}

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
