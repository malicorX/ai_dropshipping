"""Download and store Amazon product images + listing draft artifacts."""

from __future__ import annotations

import html
import json
import mimetypes
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from dropship_desk import config

_EXT_FROM_CT = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}

_JUNK_URL_MARKERS = (
    "play-icon-overlay",
    "sprite",
    "grey-pixel",
    ".SS40",
    "PKdp-play",
)


def product_dir(asin: str) -> Path:
    asin = asin.strip().upper()
    path = config.DATA_DIR / "products" / asin
    path.mkdir(parents=True, exist_ok=True)
    return path


def images_dir(asin: str) -> Path:
    path = product_dir(asin) / "images"
    path.mkdir(parents=True, exist_ok=True)
    return path


def normalize_image_url(url: str) -> str | None:
    """Drop junk thumbs; strip Amazon size suffixes for a fuller asset."""
    u = (url or "").strip()
    if not u.startswith("http"):
        return None
    low = u.lower()
    if any(m.lower() in low for m in _JUNK_URL_MARKERS):
        return None
    # e.g. ._AC_SL1500_. or ._SX300_ → prefer full image
    u = re.sub(r"\._[A-Z0-9,_+-]+_\.", ".", u, count=1)
    return u


def _guess_ext(url: str, content_type: str | None) -> str:
    if content_type:
        ct = content_type.split(";")[0].strip().lower()
        if ct in _EXT_FROM_CT:
            return _EXT_FROM_CT[ct]
    path = urlparse(url).path
    suffix = Path(path).suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        return ".jpg" if suffix == ".jpeg" else suffix
    return ".jpg"


def _looks_like_image(data: bytes, content_type: str | None) -> bool:
    if not data:
        return False
    if content_type and content_type.split(";")[0].strip().lower().startswith("image/"):
        return True
    if data[:3] == b"\xff\xd8\xff":
        return True
    if len(data) >= 8 and data[:8] == b"\x89PNG\r\n\x1a\n":
        return True
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return True
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return True
    return False


def download_product_images(
    asin: str,
    image_urls: list[str],
    *,
    force: bool = False,
    max_images: int = 8,
    timeout: float = 45.0,
) -> dict[str, Any]:
    """
    Download Amazon image URLs into data/products/{ASIN}/images/.
    Prefers Playwright's browser request stack (Amazon often resets plain httpx).
    """
    asin = asin.strip().upper()
    dest = images_dir(asin)
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in image_urls:
        n = normalize_image_url(raw)
        if not n or n in seen:
            continue
        seen.add(n)
        cleaned.append(n)
        if len(cleaned) >= max_images:
            break

    if force:
        for old in dest.glob("*"):
            if old.is_file():
                old.unlink()

    local_images: list[dict[str, str]] = []
    errors: list[str] = []

    # Reuse existing slots when not forcing
    pending: list[tuple[int, str]] = []
    for i, url in enumerate(cleaned, start=1):
        existing = _existing_slot(dest, i)
        if existing and not force:
            local_images.append(
                {
                    "index": f"{i:02d}",
                    "source_url": url,
                    "path": f"images/{existing.name}",
                    "api_path": f"/api/products/{asin}/images/{existing.name}",
                }
            )
        else:
            pending.append((i, url))

    if pending:
        fetched = _fetch_via_playwright(asin, pending, timeout=timeout)
        httpx_fallback: list[tuple[int, str]] = []
        for i, url, data, ctype, err in fetched:
            if err or not data or not _looks_like_image(data, ctype):
                httpx_fallback.append((i, url))
                if err:
                    errors.append(f"{url}: {err}")
                elif data is not None:
                    errors.append(f"{url}: response was not an image")
                continue
            _write_slot(dest, asin, i, url, data, ctype, local_images)

        for i, url in httpx_fallback:
            try:
                data, ctype = _fetch_via_httpx(asin, url, timeout=timeout)
                if not _looks_like_image(data, ctype):
                    raise RuntimeError("response was not an image")
                _write_slot(dest, asin, i, url, data, ctype, local_images)
                errors = [err for err in errors if not err.startswith(url + ":")]
            except Exception as ex:  # noqa: BLE001
                if not any(err.startswith(url + ":") for err in errors):
                    errors.append(f"{url}: {ex}")
            time.sleep(0.4)

    # Sort by index
    local_images.sort(key=lambda x: x.get("index") or "")

    media = {
        "asin": asin,
        "source_urls": cleaned,
        "local_images": local_images,
        "errors": errors[:12],
        "ok_count": len(local_images),
        "fail_count": len(errors),
    }
    (product_dir(asin) / "media.json").write_text(
        json.dumps(media, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return media


def _write_slot(
    dest: Path,
    asin: str,
    index: int,
    url: str,
    data: bytes,
    content_type: str | None,
    local_images: list[dict[str, str]],
) -> None:
    ext = _guess_ext(url, content_type)
    name = f"{index:02d}{ext}"
    for old in dest.glob(f"{index:02d}.*"):
        old.unlink()
    (dest / name).write_bytes(data)
    local_images.append(
        {
            "index": f"{index:02d}",
            "source_url": url,
            "path": f"images/{name}",
            "api_path": f"/api/products/{asin}/images/{name}",
        }
    )


def _fetch_via_playwright(
    asin: str,
    pending: list[tuple[int, str]],
    *,
    timeout: float,
) -> list[tuple[int, str, bytes | None, str | None, str | None]]:
    """Returns list of (index, url, bytes|None, content_type|None, error|None)."""
    results: list[tuple[int, str, bytes | None, str | None, str | None]] = []
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:  # noqa: BLE001
        for i, url in pending:
            results.append((i, url, None, None, f"playwright unavailable: {e}"))
        return results

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                locale="de-DE",
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                extra_http_headers={"Referer": f"https://www.amazon.de/dp/{asin}"},
            )
            # Warm CDN cookies/session via PDP visit
            page = context.new_page()
            try:
                page.goto(
                    f"https://www.amazon.de/dp/{asin}",
                    wait_until="domcontentloaded",
                    timeout=int(timeout * 1000),
                )
                time.sleep(0.8)
            except Exception:  # noqa: BLE001
                pass

            for i, url in pending:
                try:
                    resp = context.request.get(url, timeout=int(timeout * 1000))
                    if not resp.ok:
                        results.append((i, url, None, None, f"HTTP {resp.status}"))
                        continue
                    body = resp.body()
                    ctype = resp.headers.get("content-type")
                    results.append((i, url, body, ctype, None))
                except Exception as e:  # noqa: BLE001
                    results.append((i, url, None, None, str(e)))
                time.sleep(0.35)
            browser.close()
    except Exception as e:  # noqa: BLE001
        for i, url in pending:
            results.append((i, url, None, None, f"playwright failed: {e}"))
    return results


def _fetch_via_httpx(asin: str, url: str, *, timeout: float) -> tuple[bytes, str | None]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        "Referer": f"https://www.amazon.de/dp/{asin}",
        "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
    }
    last_err: Exception | None = None
    with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers, http2=False) as client:
        for attempt in range(3):
            try:
                r = client.get(url)
                r.raise_for_status()
                return r.content, r.headers.get("content-type")
            except Exception as e:  # noqa: BLE001
                last_err = e
                time.sleep(0.6 * (attempt + 1))
    raise RuntimeError(str(last_err) if last_err else "download failed")


def _existing_slot(dest: Path, index: int) -> Path | None:
    matches = sorted(dest.glob(f"{index:02d}.*"))
    return matches[0] if matches else None


def resolve_image_file(asin: str, filename: str) -> Path | None:
    asin = asin.strip().upper()
    name = Path(filename).name
    if not re.fullmatch(r"\d{2}\.[A-Za-z0-9]+", name):
        return None
    path = images_dir(asin) / name
    if not path.is_file():
        return None
    return path


def save_draft_artifacts(asin: str, draft: dict[str, Any], media: dict[str, Any] | None = None) -> dict[str, str]:
    """Write listing_draft.json + listing_draft.html under the product dir."""
    asin = asin.strip().upper()
    root = product_dir(asin)
    json_path = root / "listing_draft.json"
    html_path = root / "listing_draft.html"

    payload = dict(draft)
    if media is not None:
        payload["media"] = {
            "local_images": media.get("local_images") or [],
            "source_urls": media.get("source_urls") or [],
        }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    html_path.write_text(_render_draft_html(asin, payload), encoding="utf-8")
    return {
        "json_path": str(json_path),
        "html_path": str(html_path),
        "html_api": f"/api/products/{asin}/listing_draft.html",
        "json_api": f"/api/products/{asin}/listing_draft.json",
    }


def load_draft_artifact(asin: str) -> dict[str, Any] | None:
    path = product_dir(asin) / "listing_draft.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _render_draft_html(asin: str, draft: dict[str, Any]) -> str:
    title = html.escape(str(draft.get("title") or ""))
    subtitle = html.escape(str(draft.get("subtitle") or ""))
    bullets = draft.get("bullet_points") or []
    if isinstance(bullets, list):
        bullets_html = "".join(f"<li>{html.escape(str(b))}</li>" for b in bullets)
    else:
        bullets_html = f"<li>{html.escape(str(bullets))}</li>"
    desc = str(draft.get("description_html") or "")
    media = draft.get("media") or {}
    imgs = media.get("local_images") or []
    thumbs = []
    for img in imgs:
        api = html.escape(str(img.get("api_path") or ""))
        if api:
            thumbs.append(
                f'<img src="{api}" alt="" style="max-width:160px;margin:4px;border:1px solid #ccc" />'
            )
    plan = draft.get("image_plan") or {}
    strategy = html.escape(str(plan.get("strategy") or ""))
    model = html.escape(str(draft.get("model") or ""))

    return f"""<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="utf-8" />
  <title>{title or asin} — listing draft</title>
  <style>
    body {{ font-family: Georgia, serif; max-width: 720px; margin: 2rem auto; padding: 0 1rem; color: #1a1a1a; }}
    .meta {{ color: #666; font-size: 0.9rem; }}
    h1 {{ font-size: 1.4rem; }}
    .subtitle {{ color: #444; margin-bottom: 1.5rem; }}
    .thumbs {{ margin: 1rem 0; }}
  </style>
</head>
<body>
  <p class="meta">ASIN {html.escape(asin)} · model {model} · Dropship Desk draft artifact</p>
  <h1>{title}</h1>
  <p class="subtitle">{subtitle}</p>
  <div class="thumbs">{"".join(thumbs)}</div>
  <p class="meta">Image strategy: {strategy}</p>
  <h2>Highlights</h2>
  <ul>{bullets_html}</ul>
  <h2>Description</h2>
  <div class="desc">{desc}</div>
</body>
</html>
"""


def image_content_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(str(path))
    return guessed or "application/octet-stream"
