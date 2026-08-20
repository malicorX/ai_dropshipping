"""Authenticated HTTP helper for eBay REST APIs."""

from __future__ import annotations

from typing import Any

import httpx

from dropship_desk import config
from dropship_desk.ebay import oauth as ebay_oauth

MARKETPLACE_ID = "EBAY_DE"
CONTENT_LANGUAGE = "de-DE"


class EbayApiError(RuntimeError):
    def __init__(self, status_code: int, path: str, body: str) -> None:
        self.status_code = status_code
        self.path = path
        self.body = body
        super().__init__(f"eBay {status_code} {path}: {body[:500]}")


def _error_text(response: httpx.Response) -> str:
    try:
        data = response.json()
    except Exception:  # noqa: BLE001
        return response.text[:800]
    errors = data.get("errors") if isinstance(data, dict) else None
    if isinstance(errors, list) and errors:
        parts: list[str] = []
        for err in errors:
            if not isinstance(err, dict):
                continue
            msg = str(err.get("longMessage") or err.get("message") or "").strip()
            if msg:
                parts.append(msg)
        if parts:
            return " | ".join(parts)
    return response.text[:800]


def request(
    method: str,
    path: str,
    *,
    json_body: Any = None,
    params: dict[str, Any] | None = None,
    token: str | None = None,
    timeout: float = 45.0,
    extra_headers: dict[str, str] | None = None,
) -> Any:
    """Call api.ebay.com / sandbox REST. Returns parsed JSON or None for empty bodies."""
    headers = {
        "Authorization": f"Bearer {token or ebay_oauth.access_token()}",
        "Accept": "application/json",
        "Accept-Language": CONTENT_LANGUAGE,
        "Content-Language": CONTENT_LANGUAGE,
        "Content-Type": "application/json",
    }
    if extra_headers:
        headers.update(extra_headers)
    url = f"{config.ebay_api_base()}{path}"
    with httpx.Client(timeout=timeout) as client:
        response = client.request(
            method,
            url,
            headers=headers,
            json=json_body,
            params=params,
        )
    if response.status_code >= 400:
        raise EbayApiError(response.status_code, path, _error_text(response))
    if not response.content:
        return None
    try:
        return response.json()
    except Exception:  # noqa: BLE001
        return {"raw": response.text}


def trading_endpoint() -> str:
    if config.ebay_env() == "production":
        return "https://api.ebay.com/ws/api.dll"
    return "https://api.sandbox.ebay.com/ws/api.dll"
