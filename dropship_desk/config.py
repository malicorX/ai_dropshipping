"""Runtime configuration from environment / .env."""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

IS_FROZEN = bool(getattr(sys, "frozen", False))

if IS_FROZEN:
    RUNTIME_ROOT = Path(sys.executable).resolve().parent
else:
    RUNTIME_ROOT = Path(__file__).resolve().parent.parent

load_dotenv(RUNTIME_ROOT / ".env")

DATA_DIR = Path(os.environ.get("DROPSHIP_DATA_DIR", str(RUNTIME_ROOT / "data")))
DB_PATH = DATA_DIR / "dropship.sqlite3"

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://192.168.0.72:11435").rstrip("/")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "agents-a1-nonthink")

DEFAULT_API_PORT = int(os.environ.get("DROPSHIP_PORT", "8770"))


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def amazon_automation_enabled() -> bool:
    return _env_bool("AMAZON_AUTOMATION_ENABLED", False)


def ebay_automation_enabled() -> bool:
    return _env_bool("EBAY_AUTOMATION_ENABLED", False)


def amazon_allow_cart() -> bool:
    return _env_bool("AMAZON_ALLOW_CART", False)


def amazon_allow_purchase() -> bool:
    return _env_bool("AMAZON_ALLOW_PURCHASE", False)


def ebay_allow_list() -> bool:
    return _env_bool("EBAY_ALLOW_LIST", False)


def ebay_allow_tracking() -> bool:
    return _env_bool("EBAY_ALLOW_TRACKING", False)


def ebay_auto_publish() -> bool:
    return _env_bool("EBAY_AUTO_PUBLISH", False)


_ebay_env_override: str | None = None


def normalize_ebay_env(raw: str | None) -> str:
    value = (raw or "").strip().lower()
    if value in ("production", "prod", "prd", "live"):
        return "production"
    return "sandbox"


def set_ebay_env_override(env: str | None) -> str:
    """Runtime target from Settings. None clears the override (fall back to EBAY_ENV)."""
    global _ebay_env_override
    if env is None or str(env).strip() == "":
        _ebay_env_override = None
    else:
        _ebay_env_override = normalize_ebay_env(env)
    return ebay_env()


def ebay_env() -> str:
    if _ebay_env_override in ("sandbox", "production"):
        return _ebay_env_override
    return normalize_ebay_env(os.environ.get("EBAY_ENV", "sandbox"))


# Transport-level guard for upload runs.  A background job can observe the
# target as sandbox and then the process-wide env can flip to production
# before the first HTTP write.  The pin closes that race: every eBay transport
# helper asks this flag before opening a connection and refuses non-sandbox
# hosts while it is set.
_upload_pin_lock = threading.RLock()
_upload_sandbox_pinned = False


def pin_sandbox_for_upload(pinned: bool) -> bool:
    """Pin or release the process-wide upload sandbox transport guard."""
    global _upload_sandbox_pinned
    with _upload_pin_lock:
        _upload_sandbox_pinned = bool(pinned)
        return _upload_sandbox_pinned


def upload_sandbox_pinned() -> bool:
    """True while an upload run requires every eBay host to be the sandbox."""
    with _upload_pin_lock:
        return _upload_sandbox_pinned


def is_sandbox_host(host: str) -> bool:
    """True for every eBay sandbox hostname (api/auth/www)."""
    host = (host or "").strip().lower().rstrip(".")
    return host == "sandbox.ebay.com" or host.endswith(".sandbox.ebay.com")


def ensure_write_target_allowed(url: str) -> None:
    """Refuse a non-sandbox eBay host while an upload run is pinned.

    This lives in ``config`` (which imports no eBay transport module) so both
    ``ebay.client`` and ``ebay.oauth`` can call it without an import cycle.
    It is deliberately checked at the transport boundary, after the job's own
    target checks and immediately before any HTTP client is created.  It
    therefore still holds when ``config.ebay_env()`` flips between the job's
    check and the actual request.
    """
    if not upload_sandbox_pinned():
        return
    host = urlparse(url).hostname or ""
    if not is_sandbox_host(host):
        raise RuntimeError(
            "LIVE_WRITE_BLOCKED: upload run is pinned to the eBay sandbox; "
            f"refusing to contact {host or url}"
        )


def _ebay_credential(env: str, sandbox_key: str, prod_key: str) -> str:
    if normalize_ebay_env(env) == "production":
        return os.environ.get(prod_key, "").strip()
    return os.environ.get(sandbox_key, "").strip()


def ebay_app_id(env: str | None = None) -> str:
    return _ebay_credential(env or ebay_env(), "EBAY_SANDBOX_APP_ID", "EBAY_PROD_APP_ID")


def ebay_cert_id(env: str | None = None) -> str:
    return _ebay_credential(env or ebay_env(), "EBAY_SANDBOX_CERT_ID", "EBAY_PROD_CERT_ID")


def ebay_dev_id(env: str | None = None) -> str:
    return _ebay_credential(env or ebay_env(), "EBAY_SANDBOX_DEV_ID", "EBAY_PROD_DEV_ID")


def ebay_runame(env: str | None = None) -> str:
    return _ebay_credential(env or ebay_env(), "EBAY_SANDBOX_RUNAME", "EBAY_PROD_RUNAME")


def ebay_target_gaps(env: str | None = None) -> list[str]:
    target = normalize_ebay_env(env) if env is not None else ebay_env()
    if target == "production":
        pairs = (
            ("EBAY_PROD_APP_ID", ebay_app_id(target)),
            ("EBAY_PROD_CERT_ID", ebay_cert_id(target)),
            ("EBAY_PROD_RUNAME", ebay_runame(target)),
        )
    else:
        pairs = (
            ("EBAY_SANDBOX_APP_ID", ebay_app_id(target)),
            ("EBAY_SANDBOX_CERT_ID", ebay_cert_id(target)),
            ("EBAY_SANDBOX_RUNAME", ebay_runame(target)),
        )
    return [name for name, value in pairs if not value]


def ebay_target_ready(env: str | None = None) -> bool:
    return not ebay_target_gaps(env)


def ebay_api_base() -> str:
    if ebay_env() == "production":
        return "https://api.ebay.com"
    return "https://api.sandbox.ebay.com"


def ebay_auth_base() -> str:
    if ebay_env() == "production":
        return "https://auth.ebay.com"
    return "https://auth.sandbox.ebay.com"


def automation_snapshot() -> dict[str, bool]:
    return {
        "amazon_enabled": amazon_automation_enabled(),
        "ebay_enabled": ebay_automation_enabled(),
        "amazon_allow_cart": amazon_allow_cart(),
        "amazon_allow_purchase": amazon_allow_purchase(),
        "ebay_allow_list": ebay_allow_list(),
        "ebay_allow_tracking": ebay_allow_tracking(),
        "ebay_auto_publish": ebay_auto_publish(),
    }


def ensure_data_dir() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR
