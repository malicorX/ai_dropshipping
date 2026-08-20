"""Upload local product images to eBay Picture Services, or fall back to public URLs."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import httpx

from dropship_desk.ebay import client as ebay_http
from dropship_desk.ebay import oauth as ebay_oauth
from dropship_desk.product_media import images_dir, resolve_image_file

_NS = {"e": "urn:ebay:apis:eBLBaseComponents"}


def collect_image_urls(asin: str, draft: dict[str, Any]) -> list[str]:
    """Prefer EPS uploads of local files; otherwise Amazon/source URLs eBay can fetch."""
    uploaded = upload_local_images(asin)
    if uploaded:
        return uploaded[:12]
    sources: list[str] = []
    media = draft.get("media") or {}
    for img in media.get("local_images") or []:
        url = str(img.get("source_url") or "").strip()
        if url.startswith("http"):
            sources.append(url)
    for url in media.get("source_urls") or []:
        if str(url).startswith("http"):
            sources.append(str(url))
    plan = draft.get("image_plan") or {}
    for url in plan.get("ordered_urls") or []:
        if str(url).startswith("http"):
            sources.append(str(url))
    deduped: list[str] = []
    seen: set[str] = set()
    for url in sources:
        if url in seen:
            continue
        seen.add(url)
        deduped.append(url)
    return deduped[:12]


def upload_local_images(asin: str) -> list[str]:
    folder = images_dir(asin)
    if not folder.is_dir():
        return []
    urls: list[str] = []
    files = sorted(p for p in folder.iterdir() if p.is_file())
    for path in files:
        if resolve_image_file(asin, path.name) is None:
            continue
        try:
            urls.append(_upload_one(path))
        except Exception:  # noqa: BLE001
            continue
        if len(urls) >= 12:
            break
    return urls


def _upload_one(path: Path) -> str:
    xml_body = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<UploadSiteHostedPicturesRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
        f"<PictureName>{_xml_escape(path.stem)}</PictureName>"
        "</UploadSiteHostedPicturesRequest>"
    )
    files = {
        "XML Payload": (None, xml_body, "text/xml; charset=utf-8"),
        "file": (path.name, path.read_bytes(), "application/octet-stream"),
    }
    headers = {
        "X-EBAY-API-SITEID": "77",
        "X-EBAY-API-COMPATIBILITY-LEVEL": "1399",
        "X-EBAY-API-CALL-NAME": "UploadSiteHostedPictures",
        "X-EBAY-API-IAF-TOKEN": ebay_oauth.access_token(),
    }
    with httpx.Client(timeout=60.0) as client:
        response = client.post(ebay_http.trading_endpoint(), headers=headers, files=files)
    if response.status_code >= 400:
        raise RuntimeError(f"picture upload HTTP {response.status_code}")
    url = _full_url_from_xml(response.text)
    if not url:
        ack = _xml_text(response.text, "Ack")
        err = _xml_text(response.text, "LongMessage") or _xml_text(response.text, "ShortMessage")
        raise RuntimeError(f"picture upload failed ack={ack} {err}".strip())
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
