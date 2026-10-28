"""Upload local product images to eBay Picture Services, or fall back to public URLs."""

from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import httpx

from dropship_desk.ebay import client as ebay_http
from dropship_desk.ebay import oauth as ebay_oauth
from dropship_desk.product_media import images_dir, resolve_image_file

_NS = {"e": "urn:ebay:apis:eBLBaseComponents"}


MAX_IMAGES = 12
MAX_EDGE_PX = 1600


def collect_image_urls(asin: str, draft: dict[str, Any]) -> list[str]:
    """eBay-hosted URLs of our own re-encoded copies; never Amazon links."""
    uploaded = upload_local_images(asin)
    if not uploaded:
        raise RuntimeError(
            f"No product images could be uploaded to eBay for {asin} "
            "(Amazon image links are never sent to eBay)"
        )
    return uploaded[:MAX_IMAGES]


def upload_local_images(asin: str) -> list[str]:
    folder = images_dir(asin)
    if not folder.is_dir():
        return []
    urls: list[str] = []
    errors: list[str] = []
    files = sorted(p for p in folder.iterdir() if p.is_file())
    for path in files:
        if resolve_image_file(asin, path.name) is None:
            continue
        try:
            urls.append(_upload_one(path))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{path.name}: {exc}")
            # A closed live gate / wrong target must stop the item, not skip a photo.
            if "LIVE_WRITE_BLOCKED" in str(exc) or "token env mismatch" in str(exc):
                raise
        if len(urls) >= MAX_IMAGES:
            break
    if not urls and errors:
        raise RuntimeError("picture upload failed: " + "; ".join(errors[:3]))
    return urls


def prepare_image(path: Path) -> tuple[str, bytes]:
    """Our own copy of a product photo: neutral file name, metadata stripped,
    re-encoded (EXIF orientation applied, long edge capped, RGB JPEG)."""
    from io import BytesIO

    from PIL import Image, ImageOps

    raw = path.read_bytes()
    with Image.open(BytesIO(raw)) as img:
        img = ImageOps.exif_transpose(img)
        if img.mode != "RGB":
            background = Image.new("RGB", img.size, (255, 255, 255))
            alpha = img.convert("RGBA")
            background.paste(alpha, mask=alpha.split()[-1])
            img = background
        img.thumbnail((MAX_EDGE_PX, MAX_EDGE_PX))
        out = BytesIO()
        img.save(out, format="JPEG", quality=90, optimize=True)
    name = "img-" + hashlib.sha1(raw).hexdigest()[:12] + ".jpg"
    return name, out.getvalue()


def _upload_one(path: Path) -> str:
    name, data = prepare_image(path)
    files = {"image": (name, data, "image/jpeg")}
    endpoint = ebay_http.media_endpoint()
    # Read/bind the token first, then make the final gate the last step before
    # the socket is opened.  A flag/target flip during the token read is
    # therefore observed here.
    token = ebay_oauth.access_token()
    ebay_oauth.ensure_token_env_matches(endpoint)
    ebay_http.ensure_write_target_allowed(endpoint)
    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(timeout=60.0) as client:
        ebay_http.ensure_write_target_allowed(endpoint)  # re-check after client/TLS setup, right before dispatch
        response = client.post(endpoint, headers=headers, files=files)
    if response.status_code >= 400:
        raise RuntimeError(f"picture upload HTTP {response.status_code}: {response.text[:200]}")
    try:
        url = str(response.json().get("imageUrl") or "")
    except Exception:  # noqa: BLE001
        url = ""
    if not url.startswith("https://"):
        raise RuntimeError(f"picture upload returned no imageUrl: {response.text[:200]}")
    return url


def _full_url_from_xml(xml_text: str) -> str:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return ""
    for tag in ("FullURL", "MemberURL"):
        el = root.find(f".//e:{tag}", _NS)
        if el is not None and el.text:
            return el.text.strip()
        el = root.find(f".//{tag}")
        if el is not None and el.text:
            return el.text.strip()
    return ""


def _xml_text(xml_text: str, tag: str) -> str:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return ""
    el = root.find(f".//e:{tag}", _NS)
    if el is None:
        el = root.find(f".//{tag}")
    return (el.text or "").strip() if el is not None else ""


def _xml_escape(value: str) -> str:
    return re.sub(r"[<>&'\"]", "", value)[:40]
