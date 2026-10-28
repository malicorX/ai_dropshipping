"""Runtime configuration from environment / .env."""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

from dotenv import dotenv_values, load_dotenv

IS_FROZEN = bool(getattr(sys, "frozen", False))

if IS_FROZEN:
    RUNTIME_ROOT = Path(sys.executable).resolve().parent
else:
    RUNTIME_ROOT = Path(__file__).resolve().parent.parent

ENV_FILE = RUNTIME_ROOT / ".env"
load_dotenv(ENV_FILE)

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


# Live-gate flags must follow the operator's .env edits while the process keeps
# running.  ``load_dotenv`` only copies values into ``os.environ`` at import
# time, so a running server would otherwise never see a flip back to false.
# Read the file again at call time (cached for at most one second) and let the
# file win over the stale environment value.
LIVE_ENV_CACHE_SEC = 1.0
_live_env_lock = threading.Lock()
_live_env_cache: dict[str, object] = {
    "path": None,
    "values": {},
    "read_at": 0.0,
}


def _bool_value(raw: object, default: bool = False) -> bool:
    if raw is None:
        return default
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def _live_dotenv_values() -> dict[str, object]:
    now = time.monotonic()
    path = ENV_FILE
    with _live_env_lock:
        fresh = (
            _live_env_cache.get("path") == path
            and now - float(_live_env_cache.get("read_at") or 0.0) < LIVE_ENV_CACHE_SEC
        )
        if fresh:
            return dict(_live_env_cache.get("values") or {})
        try:
            values: dict[str, object] = dict(dotenv_values(path)) if path.is_file() else {}
        except Exception:  # noqa: BLE001 - an unreadable file must not open a gate
            values = {}
        _live_env_cache["path"] = path
        _live_env_cache["values"] = values
        _live_env_cache["read_at"] = now
        return values


def clear_live_env_cache() -> None:
    """Drop the cached .env snapshot (tests / immediately after a file edit)."""
    with _live_env_lock:
        _live_env_cache["path"] = None
        _live_env_cache["values"] = {}
        _live_env_cache["read_at"] = 0.0


def _live_env_bool(name: str, default: bool = False) -> bool:
    """Live-gate boolean: the .env file wins, os.environ is the fallback."""
    values = _live_dotenv_values()
    if name in values:
        return _bool_value(values.get(name), default)
    return _env_bool(name, default)


def amazon_automation_enabled() -> bool:
    return _env_bool("AMAZON_AUTOMATION_ENABLED", False)


def ebay_automation_enabled() -> bool:
    return _live_env_bool("EBAY_AUTOMATION_ENABLED", False)


def amazon_allow_cart() -> bool:
    return _env_bool("AMAZON_ALLOW_CART", False)


def amazon_allow_purchase() -> bool:
    return _env_bool("AMAZON_ALLOW_PURCHASE", False)


def ebay_allow_list() -> bool:
    return _live_env_bool("EBAY_ALLOW_LIST", False)



def ebay_allow_tracking() -> bool:
    return _env_bool("EBAY_ALLOW_TRACKING", False)


def ebay_auto_publish() -> bool:
    return _env_bool("EBAY_AUTO_PUBLISH", False)


# Live upload is a second, explicit master switch.  It is read at call time
# (like every other flag) so an operator can still kill a run by setting it to
# false in the environment; the worker re-checks it before every eBay write.
LIVE_MAX_PER_RUN_DEFAULT = 5
LIVE_MAX_PER_RUN_HARD_CAP = 50


def ebay_live_upload_enabled() -> bool:
    """Master switch for the guarded production upload/publish path."""
    return _live_env_bool("EBAY_LIVE_UPLOAD_ENABLED", False)


def ebay_live_max_per_run() -> int:
    """Per-run live batch cap: default 5, clamped to the code ceiling 50."""
    raw = os.environ.get("EBAY_LIVE_MAX_PER_RUN")
    if raw is None or str(raw).strip() == "":
        return LIVE_MAX_PER_RUN_DEFAULT
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return LIVE_MAX_PER_RUN_DEFAULT
    return max(0, min(value, LIVE_MAX_PER_RUN_HARD_CAP))


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
_upload_production_live_pinned = False


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


def pin_production_for_live(pinned: bool) -> bool:
    """Pin or release the inverse guard for a live (production) run.

    A live run must never reach a sandbox host, and it must abort when the
    process-wide target flips away from production while the run is active.
    The pin is set for the worker lifetime and released in ``finally``.
    """
    global _upload_production_live_pinned
    with _upload_pin_lock:
        _upload_production_live_pinned = bool(pinned)
        return _upload_production_live_pinned


def production_live_pinned() -> bool:
    """True while a live run requires every eBay host to be production."""
    with _upload_pin_lock:
        return _upload_production_live_pinned


def is_sandbox_host(host: str) -> bool:
    """True for every eBay sandbox hostname (api/auth/www)."""
    host = (host or "").strip().lower().rstrip(".")
    return host == "sandbox.ebay.com" or host.endswith(".sandbox.ebay.com")


def env_for_ebay_host(host: str) -> str:
    """The eBay env a URL host belongs to (sandbox hosts vs production)."""
    return "sandbox" if is_sandbox_host(host) else "production"


# A batch worker captures its target env at start.  State files and helper
# defaults use that captured env, never a process-wide target that may have
# been flipped while a response was in flight.
_run_env_local = threading.local()


def set_run_env(env: str | None) -> None:
    if env is None:
        try:
            del _run_env_local.env
        except AttributeError:
            pass
        return
    _run_env_local.env = normalize_ebay_env(env)


def run_env() -> str | None:
    value = getattr(_run_env_local, "env", None)
    return str(value) if value in ("sandbox", "production") else None


def state_env() -> str:
    """Env for listing/token state: the active run's env, else the current one."""
    return run_env() or ebay_env()


LIVE_WRITE_GATE_FLAG = "EBAY_LIVE_UPLOAD_ENABLED"
LIVE_WRITE_GATE_AUTOMATION = "EBAY_AUTOMATION_ENABLED"
LIVE_WRITE_GATE_ALLOW_LIST = "EBAY_ALLOW_LIST"


def live_write_gate_missing() -> list[str]:
    """Names of the closed live gates (never values) for transport checks."""
    missing: list[str] = []
    if not ebay_live_upload_enabled():
        missing.append(LIVE_WRITE_GATE_FLAG)
    if not ebay_automation_enabled():
        missing.append(LIVE_WRITE_GATE_AUTOMATION)
    if not ebay_allow_list():
        missing.append(LIVE_WRITE_GATE_ALLOW_LIST)
    return missing


def ensure_write_target_allowed(url: str) -> None:
    """Refuse the wrong eBay target / a closed live gate on every write.

    This lives in ``config`` (which imports no eBay transport module) so both
    ``ebay.client`` and ``ebay.oauth`` can call it without an import cycle.
    It is deliberately checked at the transport boundary, after the job's own
    target checks and immediately before any HTTP client is created.  It
    therefore still holds when ``config.ebay_env()`` flips between the job's
    check and the actual request.

    Sandbox runs keep blocking production exactly as before.  A live run is the
    inverse: production only, never a sandbox host or a sandbox target, and the
    live gate (master flag, automation, allow-list) is re-read on every call so
    the operator can stop a run by flipping the flag or editing .env.
    """
    sandbox_pinned = upload_sandbox_pinned()
    live_pinned = production_live_pinned()
    if not sandbox_pinned and not live_pinned:
        return
    host = urlparse(url).hostname or ""
    if sandbox_pinned and live_pinned:
        raise RuntimeError(
            "LIVE_WRITE_BLOCKED: conflicting transport pins; refusing to "
            f"contact {host or url}"
        )
    if sandbox_pinned and not is_sandbox_host(host):
        raise RuntimeError(
            "LIVE_WRITE_BLOCKED: upload run is pinned to the eBay sandbox; "
            f"refusing to contact {host or url}"
        )
    if live_pinned:
        if is_sandbox_host(host):
            raise RuntimeError(
                "LIVE_WRITE_BLOCKED: live run is pinned to eBay production; "
                f"refusing to contact {host or url}"
            )
        if ebay_env() != "production":
            raise RuntimeError(
                "LIVE_WRITE_BLOCKED: live run is pinned to eBay production "
                "but the current target changed; refusing to contact "
                f"{host or url}"
            )
        missing = live_write_gate_missing()
        if missing:
            raise RuntimeError(
                "LIVE_WRITE_BLOCKED: live gate closed ("
                + ", ".join(missing)
                + f"); refusing to contact {host or url}"
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


def automation_snapshot() -> dict[str, bool | int]:
    return {
        "amazon_enabled": amazon_automation_enabled(),
        "ebay_enabled": ebay_automation_enabled(),
        "amazon_allow_cart": amazon_allow_cart(),
        "amazon_allow_purchase": amazon_allow_purchase(),
        "ebay_allow_list": ebay_allow_list(),
        "ebay_allow_tracking": ebay_allow_tracking(),
        "ebay_auto_publish": ebay_auto_publish(),
        "ebay_live_upload_enabled": ebay_live_upload_enabled(),
        "ebay_live_max_per_run": ebay_live_max_per_run(),
    }


def ensure_data_dir() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR
