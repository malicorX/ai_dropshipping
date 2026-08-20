"""Runtime configuration from environment / .env."""

from __future__ import annotations

import os
import sys
from pathlib import Path

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


def ebay_env() -> str:
    raw = os.environ.get("EBAY_ENV", "sandbox").strip().lower()
    return "production" if raw in ("production", "prod", "prd") else "sandbox"


def ebay_app_id() -> str:
    if ebay_env() == "production":
        return os.environ.get("EBAY_PROD_APP_ID", "").strip()
    return os.environ.get("EBAY_SANDBOX_APP_ID", "").strip()


def ebay_cert_id() -> str:
    if ebay_env() == "production":
        return os.environ.get("EBAY_PROD_CERT_ID", "").strip()
    return os.environ.get("EBAY_SANDBOX_CERT_ID", "").strip()


def ebay_dev_id() -> str:
    if ebay_env() == "production":
        return os.environ.get("EBAY_PROD_DEV_ID", "").strip()
    return os.environ.get("EBAY_SANDBOX_DEV_ID", "").strip()


def ebay_runame() -> str:
    if ebay_env() == "production":
        return os.environ.get("EBAY_PROD_RUNAME", "").strip()
    return os.environ.get("EBAY_SANDBOX_RUNAME", "").strip()


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
