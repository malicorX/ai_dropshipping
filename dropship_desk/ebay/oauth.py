"""eBay OAuth 2.0 authorization-code flow. Tokens live under DATA_DIR, not git."""

from __future__ import annotations

import base64
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode, urlparse

import httpx

from dropship_desk import config

OAUTH_SCOPES = (
    "https://api.ebay.com/oauth/api_scope "
    "https://api.ebay.com/oauth/api_scope/sell.inventory "
    "https://api.ebay.com/oauth/api_scope/sell.inventory.readonly "
    "https://api.ebay.com/oauth/api_scope/sell.account "
    "https://api.ebay.com/oauth/api_scope/sell.account.readonly"
)


def token_path_for(env: str) -> Any:
    config.ensure_data_dir()
    return config.DATA_DIR / f"ebay_oauth_{config.normalize_ebay_env(env)}.json"


def token_path() -> Any:
    return token_path_for(config.ebay_env())


def load_tokens_for(env: str) -> dict[str, Any]:
    path = token_path_for(env)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def oauth_connected(env: str | None = None) -> bool:
    tokens = load_tokens_for(env or config.ebay_env())
    return bool(tokens.get("refresh_token"))


def env_for_url(url: str) -> str:
    """The eBay env a request URL host belongs to."""
    host = urlparse(url).hostname or ""
    return config.env_for_ebay_host(host)


def ensure_token_env_matches(url: str) -> str:
    """Refuse a request whose URL host and token record disagree.

    A sandbox access token must never be sent to a production URL and vice
    versa.  The record's ``env`` is checked when present; legacy records
    without an ``env`` field are accepted only when the live target has not
    changed between building the URL and dispatching the request.
    """
    request_env = env_for_url(url)
    current_env = config.ebay_env()
    if current_env != request_env:
        raise RuntimeError(
            "LIVE_WRITE_BLOCKED: token env mismatch; the eBay target changed "
            f"from {request_env} to {current_env} for host {urlparse(url).hostname}"
        )
    tokens = load_tokens_for(request_env)
    record_env = str((tokens or {}).get("env") or "").strip()
    if record_env and record_env != request_env:
        raise RuntimeError(
            "LIVE_WRITE_BLOCKED: token env mismatch; the stored "
            f"{request_env} token record says {record_env}"
        )
    return request_env


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
        "sandbox_ready": config.ebay_target_ready("sandbox"),
        "production_ready": config.ebay_target_ready("production"),
        "sandbox_gaps": config.ebay_target_gaps("sandbox"),
        "production_gaps": config.ebay_target_gaps("production"),
        "sandbox_oauth_connected": oauth_connected("sandbox"),
        "production_oauth_connected": oauth_connected("production"),
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
            f"https://127.0.0.1:{config.DEFAULT_API_PORT}/api/ebay/oauth/callback "
            "then set EBAY_SANDBOX_RUNAME (or EBAY_PROD_RUNAME) in .env"
        )
    params = {
        "client_id": app_id,
        "response_type": "code",
        "redirect_uri": runame,
        "scope": OAUTH_SCOPES,
        "prompt": "login",
        "state": config.ebay_env(),
    }
    return f"{config.ebay_auth_base()}/oauth2/authorize?{urlencode(params)}"


def load_tokens() -> dict[str, Any]:
    return load_tokens_for(config.ebay_env())


def save_tokens(payload: dict[str, Any], env: str | None = None) -> None:
    target = config.normalize_ebay_env(env or config.ebay_env())
    now = time.time()
    expires_in = int(payload.get("expires_in") or 0)
    record = {
        "access_token": payload.get("access_token"),
        "refresh_token": payload.get("refresh_token")
        or load_tokens_for(target).get("refresh_token"),
        "token_type": payload.get("token_type"),
        "expires_in": expires_in,
        "expires_at": datetime.fromtimestamp(now + expires_in, tz=timezone.utc).isoformat()
        if expires_in
        else None,
        "refresh_token_expires_in": payload.get("refresh_token_expires_in"),
        "env": target,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    token_path_for(target).write_text(json.dumps(record, indent=2), encoding="utf-8")


def _basic_auth_header() -> str:
    raw = f"{config.ebay_app_id()}:{config.ebay_cert_id()}".encode()
    return "Basic " + base64.b64encode(raw).decode("ascii")


def exchange_code(code: str) -> dict[str, Any]:
    request_env = config.ebay_env()
    runame = config.ebay_runame()
    if not runame:
        raise ValueError("EBAY_*_RUNAME is empty")
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": runame,
    }
    url = f"{config.ebay_api_base()}/identity/v1/oauth2/token"
    config.ensure_write_target_allowed(url)
    with httpx.Client(timeout=30.0) as client:
        r = client.post(
            url,
            data=data,
            headers={
                "Authorization": _basic_auth_header(),
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        if r.status_code >= 400:
            raise RuntimeError(f"eBay token exchange failed ({r.status_code}): {r.text[:400]}")
        payload = r.json()
    # The response belongs to the env captured before the request; a flip while
    # it was in flight must never write a production token into the sandbox
    # file (or vice versa).
    save_tokens(payload, env=request_env)
    return public_status()


def access_token(*, skew_seconds: int = 120) -> str:
    """Return a usable user access token, refreshing when close to expiry."""
    current_env = config.ebay_env()
    tokens = load_tokens_for(current_env)
    record_env = str(tokens.get("env") or "").strip()
    if record_env and record_env != current_env:
        raise RuntimeError(
            "LIVE_WRITE_BLOCKED: token env mismatch; the stored "
            f"{current_env} token record says {record_env}"
        )
    token = str(tokens.get("access_token") or "")
    refresh = str(tokens.get("refresh_token") or "")
    if not token and not refresh:
        raise RuntimeError("eBay is not connected — use Settings → Connect eBay")
    if token and not _token_expiring(tokens.get("expires_at"), skew_seconds=skew_seconds):
        return token
    if not refresh:
        raise RuntimeError("eBay access token expired and no refresh token is stored")
    return _refresh_access_token(refresh)


def _token_expiring(expires_at: Any, *, skew_seconds: int) -> bool:
    if not expires_at:
        return True
    try:
        exp = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
    except ValueError:
        return True
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) + timedelta(seconds=skew_seconds) >= exp


def _refresh_access_token(refresh_token: str) -> str:
    request_env = config.ebay_env()
    tokens = load_tokens_for(request_env)
    record_env = str(tokens.get("env") or "").strip()
    if record_env and record_env != request_env:
        raise RuntimeError(
            "LIVE_WRITE_BLOCKED: token env mismatch; cannot refresh a "
            f"{record_env} token against {request_env}"
        )
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "scope": OAUTH_SCOPES,
    }
    url = f"{config.ebay_api_base()}/identity/v1/oauth2/token"
    config.ensure_write_target_allowed(url)
    with httpx.Client(timeout=30.0) as client:
        r = client.post(
            url,
            data=data,
            headers={
                "Authorization": _basic_auth_header(),
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        if r.status_code >= 400:
            raise RuntimeError(f"eBay token refresh failed ({r.status_code}): {r.text[:400]}")
        payload = r.json()
    # Persist under the env the refresh was issued for, not a target that may
    # have flipped while the response was in flight.
    save_tokens(payload, env=request_env)
    token = str(payload.get("access_token") or "")
    if not token:
        raise RuntimeError("eBay token refresh returned no access_token")
    return token


_app_token_cache: dict[str, Any] = {"token": "", "expires_at": 0.0, "env": ""}


def clear_application_token_cache() -> None:
    _app_token_cache["token"] = ""
    _app_token_cache["expires_at"] = 0.0
    _app_token_cache["env"] = ""


def application_token() -> str:
    """Client-credentials token for Taxonomy (category suggestions)."""
    now = time.time()
    env = config.ebay_env()
    cached = str(_app_token_cache.get("token") or "")
    expires_at = float(_app_token_cache.get("expires_at") or 0)
    if cached and _app_token_cache.get("env") == env and now < expires_at - 60:
        return cached
    url = f"{config.ebay_api_base()}/identity/v1/oauth2/token"
    config.ensure_write_target_allowed(url)
    with httpx.Client(timeout=30.0) as client:
        r = client.post(
            url,
            data={
                "grant_type": "client_credentials",
                "scope": "https://api.ebay.com/oauth/api_scope",
            },
            headers={
                "Authorization": _basic_auth_header(),
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        if r.status_code >= 400:
            raise RuntimeError(f"eBay application token failed ({r.status_code}): {r.text[:400]}")
        payload = r.json()
    token = str(payload.get("access_token") or "")
    if not token:
        raise RuntimeError("eBay application token missing")
    _app_token_cache["token"] = token
    _app_token_cache["expires_at"] = now + float(payload.get("expires_in") or 7200)
    _app_token_cache["env"] = env
    return token
