"""eBay OAuth 2.0 authorization-code flow. Tokens live under DATA_DIR, not git."""

from __future__ import annotations

import base64
import json
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

import httpx

from dropship_desk import config

OAUTH_SCOPES = (
    "https://api.ebay.com/oauth/api_scope "
    "https://api.ebay.com/oauth/api_scope/sell.inventory "
    "https://api.ebay.com/oauth/api_scope/sell.inventory.readonly "
    "https://api.ebay.com/oauth/api_scope/sell.account "
    "https://api.ebay.com/oauth/api_scope/sell.account.readonly"
)


def token_path() -> Any:
    config.ensure_data_dir()
    env = config.ebay_env()
    return config.DATA_DIR / f"ebay_oauth_{env}.json"


def _mask(value: str, keep: int = 6) -> str:
    if not value:
        return ""
    if len(value) <= keep:
        return "…"
    return value[:keep] + "…"


def public_status() -> dict[str, Any]:
    tokens = load_tokens()
    expiry = tokens.get("expires_at") if tokens else None
    connected = bool(tokens and tokens.get("refresh_token"))
    return {
        "env": config.ebay_env(),
        "api_base": config.ebay_api_base(),
        "app_id_set": bool(config.ebay_app_id()),
        "cert_id_set": bool(config.ebay_cert_id()),
        "dev_id_set": bool(config.ebay_dev_id()),
        "app_id_hint": _mask(config.ebay_app_id()),
        "runame_set": bool(config.ebay_runame()),
        "oauth_connected": connected,
        "token_expires_at": expiry,
        "auto_publish": config.ebay_auto_publish(),
        "automation_enabled": config.ebay_automation_enabled(),
        "allow_list": config.ebay_allow_list(),
    }


def authorize_url() -> str:
    runame = config.ebay_runame()
    app_id = config.ebay_app_id()
    if not app_id:
        raise ValueError("eBay App ID missing in .env for current EBAY_ENV")
    if not runame:
        raise ValueError(
            "eBay RuName missing. In developer.ebay.com → your app → User tokens, "
            "create an OAuth RuName whose Auth accepted URL is "
            f"http://127.0.0.1:{config.DEFAULT_API_PORT}/api/ebay/oauth/callback "
            "then set EBAY_SANDBOX_RUNAME (or EBAY_PROD_RUNAME) in .env"
        )
    params = {
        "client_id": app_id,
        "response_type": "code",
        "redirect_uri": runame,
        "scope": OAUTH_SCOPES,
        "prompt": "login",
    }
    return f"{config.ebay_auth_base()}/oauth2/authorize?{urlencode(params)}"


def load_tokens() -> dict[str, Any]:
    path = token_path()
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_tokens(payload: dict[str, Any]) -> None:
    now = time.time()
    expires_in = int(payload.get("expires_in") or 0)
    record = {
        "access_token": payload.get("access_token"),
        "refresh_token": payload.get("refresh_token") or load_tokens().get("refresh_token"),
        "token_type": payload.get("token_type"),
        "expires_in": expires_in,
        "expires_at": datetime.fromtimestamp(now + expires_in, tz=timezone.utc).isoformat()
        if expires_in
        else None,
        "refresh_token_expires_in": payload.get("refresh_token_expires_in"),
        "env": config.ebay_env(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    token_path().write_text(json.dumps(record, indent=2), encoding="utf-8")


def _basic_auth_header() -> str:
    raw = f"{config.ebay_app_id()}:{config.ebay_cert_id()}".encode()
    return "Basic " + base64.b64encode(raw).decode("ascii")


def exchange_code(code: str) -> dict[str, Any]:
    runame = config.ebay_runame()
    if not runame:
        raise ValueError("EBAY_*_RUNAME is empty")
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": runame,
    }
    with httpx.Client(timeout=30.0) as client:
        r = client.post(
            f"{config.ebay_api_base()}/identity/v1/oauth2/token",
            data=data,
            headers={
                "Authorization": _basic_auth_header(),
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        if r.status_code >= 400:
            raise RuntimeError(f"eBay token exchange failed ({r.status_code}): {r.text[:400]}")
        payload = r.json()
    save_tokens(payload)
    return public_status()
