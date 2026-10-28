"""Read upload_items.txt and publish each Amazon link as an eBay listing.

The file is the operator's batch queue: one Amazon.de link (or bare ASIN) per
line.  The job is intentionally sequential and single-flight, and it refuses to
run in production until live writes are explicitly enabled by the operator.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
from typing import Any

from dropship_desk import config
from dropship_desk.amazon.product import (
    AmazonUnreachable,
    AsinNotFound,
    ChromeNotFound,
    fetch_variation_offers,
)
from dropship_desk.asin import extract_asin
from dropship_desk.db import get_candidate_by_asin, save_listing_draft
from dropship_desk.ebay import listing as ebay_listing
from dropship_desk.ebay import oauth as ebay_oauth
from dropship_desk.evaluate_service import run_evaluate
from dropship_desk.listing_generate import (
    ListingGenerateError,
    VariationParentError,
    generate_draft,
)
from dropship_desk.models import EvaluateRequest, OfferIn

ROW_STATES = (
    "queued",
    "fetching",
    "evaluated",
    "drafted",
    "prepared",
    "staged",
    "published",
    "skipped_existing",
    "not_prepared",
    "not_found",
    "rejected",
    "error",
    "duplicate_in_file",
)
_TERMINAL_STATES = frozenset(ROW_STATES) - {"queued", "fetching"}
EXISTING_REASON = "haben wir schon"
PREPARED_REASON = "haben wir schon (vorbereitet)"
TITLE_LIMIT = 80
VARIATION_SEPARATOR = " - "
DEFAULT_UPLOAD_FILE = "upload_items.txt"
# Retries are disabled (operator 2026-10-28): every row is tried exactly once.
# Raise MAX_RETRY_PASSES to re-enable bounded extra passes for AMAZON_UNREACHABLE.
MAX_RETRY_PASSES = 0
RETRY_PASS_PAUSE_SEC = 30
RETRYABLE_ERROR_PREFIX = "AMAZON_UNREACHABLE"
_RETRY_PAUSE_STEP_SEC = 0.25
_ASIN_RE = re.compile(r"^[A-Z0-9]{10}$")

# Live-gate item names are config/env identifiers only (no secrets, no values).
LIVE_MISSING_ENV = "EBAY_ENV"
LIVE_MISSING_FLAG = "EBAY_LIVE_UPLOAD_ENABLED"
LIVE_MISSING_AUTOMATION = "EBAY_AUTOMATION_ENABLED"
LIVE_MISSING_ALLOW_LIST = "EBAY_ALLOW_LIST"
LIVE_MISSING_ACCOUNT = "EBAY_PRODUCTION_ACCOUNT"
LIVE_MODE_UPLOAD = "upload"
LIVE_MODE_PUBLISH = "publish"
LIVE_AUDIT_FILENAME = "live_audit.jsonl"
# A live plan is confirmed by a server-issued, single-use nonce that expires
# after ten minutes.  It is kept in memory only; a restart invalidates plans.
LIVE_NONCE_TTL_SEC = 600.0
LIVE_NONCE_STORE_LIMIT = 32
_live_nonce_lock = threading.Lock()
_live_nonces: dict[str, dict[str, Any]] = {}


def normalize_asin(value: Any) -> str:
    """Return a canonical ASIN for a string input, else an empty string.

    Publishing accepts operator/API input, so this is the trust boundary: it
    must never pass a path fragment such as ``../../ESCB3B6D7`` on to the
    product-directory/listing-state helpers.
    """
    if not isinstance(value, str):
        return ""
    candidate = value.strip().upper()
    return candidate if _ASIN_RE.fullmatch(candidate) else ""


class UploadFileMissing(FileNotFoundError):
    """The configured upload file does not exist."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        super().__init__(f"UPLOAD_FILE_MISSING: {self.path}")


class InvalidUploadFile(ValueError):
    """A requested upload file name is not a bare ``*.txt`` inside the folder."""

    def __init__(self, name: Any) -> None:
        self.name = str(name)
        super().__init__(
            f"INVALID_UPLOAD_FILE: {self.name!r} is not a .txt file directly "
            f"inside {upload_items_dir()}"
        )


class UploadAlreadyRunning(RuntimeError):
    """A second start was requested while the single-flight job is running."""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        super().__init__(f"Upload already running (run_id={run_id})")


class LiveUploadDisabled(RuntimeError):
    """Production is refused before any network call.

    ``missing`` carries config/env names only (never values) so the API/UI can
    tell the operator exactly which gate is closed.
    """

    def __init__(self, message: str, missing: list[str] | None = None) -> None:
        self.missing = list(missing or [])
        super().__init__(message)


class LiveConfirmMismatch(RuntimeError):
    """The typed confirmation or batch hash does not match the server batch."""


class LiveCapExceeded(RuntimeError):
    """The server-computed batch is larger than the live cap."""

    def __init__(self, n: int, cap: int) -> None:
        self.n = n
        self.cap = cap
        super().__init__(f"LIVE_CAP_EXCEEDED: batch has {n} ASINs, cap is {cap}")


class LiveAuditError(RuntimeError):
    """The append-only live audit log could not be written."""


class _LiveDisabled(RuntimeError):
    """The live master switch/gate was closed while the run was active."""


class NotSignedIn(RuntimeError):
    """Sandbox uploads need a connected eBay account."""


class _AbortRun(RuntimeError):
    """A systemic fetch failure: stop the whole batch."""


class _TargetChanged(RuntimeError):
    """The eBay target changed while the batch was running."""


@dataclass
class UploadRow:
    line_no: int
    line: str
    asin: str = ""
    state: str = "queued"
    reason: str = ""
    offer_id: str = ""
    listing_id: str = ""
    item_url: str = ""
    price: float | None = None
    started_at: str = ""
    finished_at: str = ""
    duration_sec: float | None = None
    attempts: int = 1
    _started_monotonic: float | None = field(
        default=None, repr=False, compare=False
    )
    _audited: bool = field(default=False, repr=False, compare=False)
    _intent_audited: bool = field(default=False, repr=False, compare=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "line_no": self.line_no,
            "line": self.line,
            "asin": self.asin,
            "state": self.state,
            "reason": self.reason,
            "offer_id": self.offer_id,
            "listing_id": self.listing_id,
            "item_url": self.item_url,
            "price": self.price,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_sec": self.duration_sec,
            "attempts": self.attempts,
        }


def _listing_id(state: dict[str, Any]) -> str:
    return str(state.get("listing_id") or "")


def _item_url(state: dict[str, Any]) -> str:
    saved = str(state.get("item_url") or "")
    if saved:
        return saved
    listing_id = _listing_id(state)
    return ebay_listing.item_url(listing_id) if listing_id else ""


def _state_price(state: dict[str, Any]) -> float | None:
    raw = state.get("price")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def published_listing_state(asin: str, env: str) -> dict[str, Any] | None:
    """Return the saved listing when ``asin`` is already published for ``env``.

    This is a local, file-only read (no network).  Sandbox and production keep
    separate state files; the stored ``env`` is checked as a second guard for
    legacy records that predate the per-env file split.
    """
    target = (env or "").strip()
    try:
        state = ebay_listing.load_listing_state(asin, env=target or None)
    except OSError:
        return None
    if str(state.get("status") or "") != "published":
        return None
    state_env = str(state.get("env") or "").strip()
    if state_env and target and state_env != target:
        return None
    return state


def mark_row_listed(row: UploadRow, state: dict[str, Any], *, row_state: str) -> None:
    """Copy the known offer/listing identity onto a row and mark it as seen."""
    row.state = row_state
    row.reason = EXISTING_REASON
    row.offer_id = str(state.get("offer_id") or "")
    row.listing_id = _listing_id(state)
    row.item_url = _item_url(state)
    row.price = _state_price(state)


def draft_title_for(asin: str) -> str:
    """The stored draft title for ``asin`` (empty when there is no draft)."""
    row = get_candidate_by_asin(asin)
    draft = (row or {}).get("listing_draft") or {}
    if not isinstance(draft, dict):
        return ""
    return str(draft.get("title") or "").strip()


def already_prepared(asin: str, env: str) -> bool:
    """True when a draft exists and the ASIN is not published for ``env``.

    This is a local, file/DB-only read: it lets a second prepare run skip the
    ASIN before any Amazon fetch or LLM call.
    """
    if published_listing_state(asin, env) is not None:
        return False
    return bool(draft_title_for(asin))


def upload_items_path() -> Path:
    """The operator file, honouring the UPLOAD_ITEMS_FILE override."""
    override = (os.environ.get("UPLOAD_ITEMS_FILE") or "").strip()
    if override:
        return Path(override)
    return upload_items_dir() / DEFAULT_UPLOAD_FILE


def _upload_override() -> str:
    return (os.environ.get("UPLOAD_ITEMS_FILE") or "").strip()


def upload_items_dir() -> Path:
    """Folder that holds selectable ``*.txt`` upload lists (non-recursive)."""
    override = _upload_override()
    if override:
        return Path(override).parent
    return config.RUNTIME_ROOT / "upload_items"


def _invalid_name(name: Any) -> bool:
    """True unless ``name`` is a bare ``*.txt`` file name (no path parts).

    A colon is always refused: on Windows ``name.txt:stream`` addresses an
    alternate data stream and would read bytes that never appear in a normal
    listing of the folder.
    """
    if not isinstance(name, str):
        return True
    if not name or name != name.strip():
        return True
    if "/" in name or "\\" in name or ":" in name:
        return True
    # ``..`` anywhere is refused, not only as a whole component.
    if ".." in name or name in (".", ".."):
        return True
    if os.path.isabs(name) or PureWindowsPath(name).is_absolute():
        return True
    if PureWindowsPath(name).drive or PureWindowsPath(name).root:
        return True
    if Path(name).name != name:
        return True
    return Path(name).suffix.lower() != ".txt"


def _is_reparse_point(path: Path) -> bool:
    """True for Windows reparse points (junctions, mount points, ...)."""
    try:
        info = path.stat(follow_symlinks=False)
    except (OSError, ValueError, NotImplementedError):
        return False
    attributes = getattr(info, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & reparse_flag)


def resolve_upload_file(name: str | None = None) -> Path:
    """Resolve an optional bare file name to an existing file in the folder.

    ``None``/empty keeps the historical default (``upload_items.txt`` or the
    ``UPLOAD_ITEMS_FILE`` override).  An explicitly supplied name is a trust
    boundary: it must be a bare ``*.txt`` file name resolving directly inside
    ``upload_items_dir()``.  Nothing is read before this validation passes.
    Whitespace-only names are not "empty": they are rejected rather than
    silently falling back to the default.
    """
    if name is None or name == "":
        return upload_items_path()
    if _invalid_name(name):
        raise InvalidUploadFile(name)
    assert isinstance(name, str)
    base = upload_items_dir().resolve()
    candidate = (base / name).resolve()
    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise InvalidUploadFile(name) from exc
    if candidate.parent != base or not candidate.is_file():
        raise InvalidUploadFile(name)
    return candidate


def list_upload_files() -> dict[str, Any]:
    """List the ``*.txt`` lists directly inside the upload folder, newest first.

    Entries whose name is not a plain ``*.txt`` file name are skipped before
    any filesystem access, and symlinks/reparse points are never followed for
    size, line count or mtime.
    """
    base = upload_items_dir()
    entries: list[dict[str, Any]] = []
    try:
        children = list(base.iterdir())
    except OSError:
        children = []
    for path in children:
        if _invalid_name(path.name):
            continue
        try:
            if path.is_symlink() or _is_reparse_point(path):
                continue
            if not path.is_file():
                continue
            info = path.stat()
            text = path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            continue
        entries.append(
            {
                "name": path.name,
                "size": info.st_size,
                "modified": datetime.fromtimestamp(
                    info.st_mtime, timezone.utc
                ).isoformat(),
                "lines": len(text.splitlines()),
                "_mtime": info.st_mtime,
            }
        )
    entries.sort(key=lambda entry: entry["_mtime"], reverse=True)
    for entry in entries:
        entry.pop("_mtime", None)
    names = [entry["name"] for entry in entries]
    override = _upload_override()
    if override:
        override_name = Path(override).name
        if override_name in names:
            default = override_name
        elif DEFAULT_UPLOAD_FILE in names:
            default = DEFAULT_UPLOAD_FILE
        else:
            default = names[0] if names else override_name
    elif DEFAULT_UPLOAD_FILE in names:
        default = DEFAULT_UPLOAD_FILE
    else:
        default = names[0] if names else DEFAULT_UPLOAD_FILE
    return {"dir": str(base), "default": default, "files": entries}


def parse_upload_text(text: str) -> list[UploadRow]:
    """Parse already-read upload text (keeps hash and rows from one snapshot)."""
    rows: list[UploadRow] = []
    first_line_by_asin: dict[str, int] = {}
    for line_no, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        asin = extract_asin(line)
        if not asin:
            rows.append(
                UploadRow(line_no=line_no, line=raw, state="rejected", reason="no_asin")
            )
            continue
        if asin in first_line_by_asin:
            rows.append(
                UploadRow(
                    line_no=line_no,
                    line=raw,
                    asin=asin,
                    state="duplicate_in_file",
                    reason=f"duplicate of line {first_line_by_asin[asin]}",
                )
            )
            continue
        first_line_by_asin[asin] = line_no
        rows.append(UploadRow(line_no=line_no, line=raw, asin=asin, state="queued"))
    return rows


def read_upload_file(path: str | Path | None = None) -> list[UploadRow]:
    """Parse the upload file, deduping ASINs without dropping the original line."""
    target = Path(path) if path is not None else upload_items_path()
    if not target.is_file():
        raise UploadFileMissing(target)
    text = target.read_text(encoding="utf-8-sig", errors="replace")
    return parse_upload_text(text)


def read_upload_snapshot(path: Path) -> tuple[list[UploadRow], str]:
    """Read bytes once: rows and the content hash describe the same file state."""
    target = Path(path)
    if not target.is_file():
        raise UploadFileMissing(target)
    raw = target.read_bytes()
    text = raw.decode("utf-8-sig", errors="replace")
    return parse_upload_text(text), hashlib.sha256(raw).hexdigest()


# --------------------------------------------------------------- live gate


def live_gate_missing(env: str | None = None) -> list[str]:
    """Names of every closed live gate (never values/secrets)."""
    target = config.normalize_ebay_env(
        env if env is not None else config.operation_env()
    )
    missing: list[str] = []
    if target != "production":
        missing.append(LIVE_MISSING_ENV)
    if not config.ebay_live_upload_enabled():
        missing.append(LIVE_MISSING_FLAG)
    if not config.ebay_automation_enabled():
        missing.append(LIVE_MISSING_AUTOMATION)
    if not config.ebay_allow_list():
        missing.append(LIVE_MISSING_ALLOW_LIST)
    try:
        connected = bool(ebay_oauth.oauth_connected("production"))
    except Exception:  # noqa: BLE001 - an unreadable token is a closed gate
        connected = False
    if not connected:
        missing.append(LIVE_MISSING_ACCOUNT)
    return missing


def live_gate_message(missing: list[str]) -> str:
    if not missing:
        return "LIVE_UPLOAD_DISABLED: the live upload path is not available"
    return "LIVE_UPLOAD_DISABLED: missing " + ", ".join(missing)


def _normalize_live_mode(mode: Any) -> str:
    value = str(mode or "").strip().lower()
    if value in ("upload", "full", "file"):
        return LIVE_MODE_UPLOAD
    if value in ("publish", "prepared", "asins"):
        return LIVE_MODE_PUBLISH
    raise ValueError(f"unknown live plan mode {mode!r} (use 'upload' or 'publish')")


def compute_batch_hash(
    *,
    mode: str,
    env: str,
    asins: list[str],
    file_name: str = "",
    file_hash: str = "",
) -> str:
    """Canonical sha256 over env + sorted ASINs (+ upload file identity)."""
    payload: dict[str, Any] = {
        "schema": 1,
        "mode": mode,
        "env": config.normalize_ebay_env(env),
        "asins": sorted(asins),
    }
    if mode == LIVE_MODE_UPLOAD:
        payload["file_name"] = file_name
        payload["file_hash"] = file_hash
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def clear_live_nonces() -> None:
    """Drop every outstanding plan nonce (tests; also useful after a target switch)."""
    with _live_nonce_lock:
        _live_nonces.clear()


def _prune_live_nonces(now: float | None = None) -> None:
    moment = _monotonic() if now is None else now
    expired = [
        nonce
        for nonce, record in _live_nonces.items()
        if moment - float(record.get("issued_at") or 0.0) > LIVE_NONCE_TTL_SEC
    ]
    for nonce in expired:
        _live_nonces.pop(nonce, None)


def issue_live_nonce(*, mode: str, env: str, batch_hash: str, n: int | None = None) -> str:
    """Server-generated, single-use confirmation nonce for one plan.

    The store is bounded: older plans are dropped once 32 are outstanding.
    """
    nonce = secrets.token_urlsafe(24)
    with _live_nonce_lock:
        _prune_live_nonces()
        while len(_live_nonces) >= LIVE_NONCE_STORE_LIMIT:
            oldest = next(iter(_live_nonces), None)
            if oldest is None:
                break
            _live_nonces.pop(oldest, None)
        _live_nonces[nonce] = {
            "mode": mode,
            "env": config.normalize_ebay_env(env),
            "batch_hash": batch_hash,
            "n": n,
            "issued_at": _monotonic(),
        }
    return nonce


def _nonce_mismatch(
    record: dict[str, Any],
    *,
    mode: str,
    env: str,
    batch_hash: str,
    n: int | None,
    supplied_hash: str | None,
) -> bool:
    return bool(
        record.get("batch_hash") != batch_hash
        or record.get("mode") != mode
        or record.get("env") != config.normalize_ebay_env(env)
        or (n is not None and record.get("n") is not None and record.get("n") != n)
        or (supplied_hash is not None and supplied_hash != batch_hash)
    )


def _burn_live_nonce(nonce: Any) -> None:
    """Drop a nonce (used when an attempt was rejected)."""
    if not isinstance(nonce, str) or not nonce:
        return
    with _live_nonce_lock:
        _live_nonces.pop(nonce, None)


def validate_live_nonce(
    nonce: Any,
    *,
    mode: str,
    env: str,
    batch_hash: str,
    n: int | None = None,
    supplied_hash: str | None = None,
) -> None:
    """Check a nonce atomically; a changed batch/n burns it even on rejection."""
    if not isinstance(nonce, str) or not nonce:
        raise LiveConfirmMismatch(
            "LIVE_CONFIRM_MISMATCH: plan nonce missing; request a fresh plan"
        )
    with _live_nonce_lock:
        _prune_live_nonces()
        record = _live_nonces.get(nonce)
        if record is None:
            raise LiveConfirmMismatch(
                "LIVE_CONFIRM_MISMATCH: plan nonce is unknown, expired or already used"
            )
        if _nonce_mismatch(
            record,
            mode=mode,
            env=env,
            batch_hash=batch_hash,
            n=n,
            supplied_hash=supplied_hash,
        ):
            # Single use even when the attempt is rejected: a stale nonce must
            # never be replayable against a different batch.
            _live_nonces.pop(nonce, None)
            raise LiveConfirmMismatch(
                "LIVE_CONFIRM_MISMATCH: plan nonce was issued for a different batch"
            )


def consume_live_nonce(
    nonce: Any,
    *,
    mode: str,
    env: str,
    batch_hash: str,
    n: int | None = None,
) -> None:
    """Atomically validate and burn a nonce; only a successful start reaches this."""
    if not isinstance(nonce, str) or not nonce:
        raise LiveConfirmMismatch(
            "LIVE_CONFIRM_MISMATCH: plan nonce missing; request a fresh plan"
        )
    with _live_nonce_lock:
        _prune_live_nonces()
        record = _live_nonces.get(nonce)
        if record is None:
            raise LiveConfirmMismatch(
                "LIVE_CONFIRM_MISMATCH: plan nonce is unknown, expired or already used"
            )
        if _nonce_mismatch(
            record,
            mode=mode,
            env=env,
            batch_hash=batch_hash,
            n=n,
            supplied_hash=None,
        ):
            _live_nonces.pop(nonce, None)
            raise LiveConfirmMismatch(
                "LIVE_CONFIRM_MISMATCH: plan nonce was issued for a different batch"
            )
        _live_nonces.pop(nonce, None)



def _unique_valid_asins(values: Any) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in list(values or []):
        asin = normalize_asin(raw)
        if not asin or asin in seen:
            continue
        seen.add(asin)
        normalized.append(asin)
    return normalized


def _plan_item(asin: str) -> dict[str, Any]:
    try:
        candidate = get_candidate_by_asin(asin) or {}
    except Exception:  # noqa: BLE001 - planning must not fail on a missing DB row
        candidate = {}
    draft = candidate.get("listing_draft") or {}
    title = ""
    if isinstance(draft, dict):
        title = str(draft.get("title") or "").strip()
    if not title:
        title = str(candidate.get("title") or "").strip()
    raw_price = candidate.get("ebay_price")
    try:
        price = float(raw_price) if raw_price is not None else None
    except (TypeError, ValueError):
        price = None
    return {"asin": asin, "title": title, "price": price}


def plan_live_batch(
    *,
    mode: Any,
    file: str | None = None,
    asins: Any = None,
    env: str | None = None,
) -> dict[str, Any]:
    """Read-only plan: server-computed n + batch hash, never an eBay call."""
    target = config.normalize_ebay_env(env if env is not None else config.ebay_env())
    normalized_mode = _normalize_live_mode(mode)
    file_name = ""
    file_hash = ""
    if normalized_mode == LIVE_MODE_UPLOAD:
        path = resolve_upload_file(file)
        rows, file_hash = read_upload_snapshot(path)
        selected = [row.asin for row in rows if row.state == "queued"]
        file_name = path.name
    else:
        selected = _unique_valid_asins(asins)
        if not selected:
            raise ValueError("asins required (non-empty list of valid ASINs)")
    batch_hash = compute_batch_hash(
        mode=normalized_mode,
        env=target,
        asins=selected,
        file_name=file_name,
        file_hash=file_hash,
    )
    items = [_plan_item(asin) for asin in selected]
    total = round(sum(item["price"] for item in items if item["price"] is not None), 2)
    missing = live_gate_missing(target)
    nonce = issue_live_nonce(
        mode=normalized_mode, env=target, batch_hash=batch_hash, n=len(selected)
    )
    return {
        "mode": normalized_mode,
        "env": target,
        "n": len(selected),
        "batch_hash": batch_hash,
        "nonce": nonce,
        "cap": config.ebay_live_max_per_run(),
        "items": items,
        "total": total,
        "live_enabled": not missing,
        "live_missing": missing,
    }


def _validate_live_confirmation(
    confirm: Any,
    n: int,
    batch_hash: Any,
    expected_hash: str,
) -> None:
    # Deliberately exact: no trim, no case folding, no client-supplied n.
    if not isinstance(confirm, str) or confirm != f"LIVE {n}":
        raise LiveConfirmMismatch(
            "LIVE_CONFIRM_MISMATCH: type LIVE <n> exactly for the planned batch"
        )
    if not isinstance(batch_hash, str) or batch_hash != expected_hash:
        raise LiveConfirmMismatch(
            "LIVE_CONFIRM_MISMATCH: batch hash does not match the current plan"
        )


# --------------------------------------------------------------- live audit


def live_audit_path() -> Path:
    return Path(config.DATA_DIR) / LIVE_AUDIT_FILENAME


def append_live_audit(entry: dict[str, Any]) -> None:
    """Append one JSON line; any failure is fatal to the live run."""
    path = live_audit_path()
    try:
        config.ensure_data_dir()
        line = json.dumps(dict(entry), ensure_ascii=False, sort_keys=True, default=str)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line + "\n")
            handle.flush()
    except Exception as exc:  # noqa: BLE001
        raise LiveAuditError(f"LIVE_AUDIT_FAILED: {exc}") from exc


def _append_live_audit_strict(entry: dict[str, Any]) -> None:
    """Call the append hook but normalise every failure to LiveAuditError."""
    try:
        append_live_audit(entry)
    except LiveAuditError:
        raise
    except Exception as exc:  # noqa: BLE001 - any append failure aborts the run
        raise LiveAuditError(f"LIVE_AUDIT_FAILED: {exc}") from exc


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _monotonic() -> float:
    """Indirection so tests can replace the clock behind ``time.monotonic``."""
    return time.monotonic()


def title_with_variation(title: str, variation_label: str) -> str:
    """Deterministically append an Amazon variation label to a draft title.

    The base is clipped so the full title stays within eBay's 80-char limit;
    the label itself is preserved.  A title that already contains the label
    (case-insensitive) is returned unchanged.
    """
    base = re.sub(r"\s+", " ", str(title or "")).strip()
    label = str(variation_label or "").strip()
    if not label or label.lower() in base.lower():
        return base
    suffix = f"{VARIATION_SEPARATOR}{label}"
    room = TITLE_LIMIT - len(suffix)
    if room <= 0:
        # Pathological label: keep the label intact rather than truncating it.
        return suffix.strip()
    clipped = base[:room].rstrip()
    return f"{clipped}{suffix}" if clipped else suffix.strip()


@dataclass
class UploadJobState:
    run_id: str = ""
    target_env: str = ""
    started_at: str = ""
    running: bool = False
    stop_requested: bool = False
    phase: str = "idle"
    mode: str = "full"
    error: str = ""
    file: str = ""
    retry_pass: int = 0
    live: bool = False
    batch_hash: str = ""
    live_cap: int = 0
    planned: int = 0
    rows: list[UploadRow] = field(default_factory=list)

    def counters(self) -> dict[str, int]:
        counts = {state: 0 for state in ROW_STATES}
        for row in self.rows:
            counts[row.state] = counts.get(row.state, 0) + 1
        counts["total"] = len(self.rows)
        counts["done"] = sum(1 for row in self.rows if row.state in _TERMINAL_STATES)
        return counts

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "target_env": self.target_env,
            "started_at": self.started_at,
            "running": self.running,
            "stop_requested": self.stop_requested,
            "phase": self.phase,
            "mode": self.mode,
            "error": self.error,
            "file": self.file,
            "retry_pass": self.retry_pass,
            "live": self.live,
            "batch_hash": self.batch_hash,
            "live_cap": self.live_cap,
            "planned": self.planned,
            "rows": [row.to_dict() for row in self.rows],
            "counters": self.counters(),
        }


def _reason(exc: BaseException) -> str:
    return str(exc).strip() or type(exc).__name__


def _is_not_found(exc: BaseException) -> bool:
    return isinstance(exc, AsinNotFound) or "ASIN_NOT_FOUND" in str(exc).upper()


def _is_failure_cap(exc: BaseException) -> bool:
    return "failure cap" in str(exc).lower()


def _is_systemic(exc: BaseException) -> bool:
    """Only Chrome failure or the process-wide fetch cap stops the batch.

    An ordinary ``AMAZON_UNREACHABLE`` belongs to one ASIN: it is a row error
    and the next line still runs.
    """
    text = str(exc).upper()
    return (
        isinstance(exc, ChromeNotFound)
        or "CHROME_NOT_FOUND" in text
        or (isinstance(exc, AmazonUnreachable) and _is_failure_cap(exc))
        or ("AMAZON_UNREACHABLE" in text and _is_failure_cap(exc))
    )


def _is_live_write_blocked(exc: BaseException) -> bool:
    return "LIVE_WRITE_BLOCKED" in str(exc).upper()


class UploadJobManager:
    """Sequential, single-flight batch runner modelled on ENRICH_JOB."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.state = UploadJobState()
        self._thread: threading.Thread | None = None

    def status(self) -> dict[str, Any]:
        with self._lock:
            return self.state.to_dict()

    def start(
        self,
        mode: str = "full",
        file: str | None = None,
        confirm: str | None = None,
        batch_hash: str | None = None,
        plan_nonce: str | None = None,
    ) -> dict[str, Any]:
        mode = str(mode or "full").strip().lower()
        if mode not in ("full", "prepare"):
            raise ValueError(f"unknown upload mode {mode!r} (use 'full' or 'prepare')")
        env = config.ebay_env()
        production = env == "production"
        if production:
            # Gate first: no file read, no OAuth, no network when anything is
            # closed.  The worker re-checks the same gates before every row.
            missing = live_gate_missing(env)
            if missing:
                raise LiveUploadDisabled(live_gate_message(missing), missing)
        # Trust boundary: an explicit name is validated before any file read.
        path = resolve_upload_file(file)

        with self._lock:
            if self.state.running:
                raise UploadAlreadyRunning(self.state.run_id)
            file_hash = ""
            if production:
                # Hash and rows must describe one file snapshot.
                rows, file_hash = read_upload_snapshot(path)
            else:
                rows = read_upload_file(path)
            planned_rows = [row for row in rows if row.state == "queued"]
            n = len(planned_rows)
            live_run = production and mode == "full"
            cap = config.ebay_live_max_per_run() if live_run else 0
            computed_hash = ""
            if production:
                computed_hash = compute_batch_hash(
                    mode=LIVE_MODE_UPLOAD,
                    env=env,
                    asins=[row.asin for row in planned_rows],
                    file_name=path.name,
                    file_hash=file_hash,
                )
            if live_run:
                # n is always server-computed from the file; never the client.
                if n > cap:
                    raise LiveCapExceeded(n, cap)
                try:
                    validate_live_nonce(
                        plan_nonce,
                        mode=LIVE_MODE_UPLOAD,
                        env=env,
                        batch_hash=computed_hash,
                        n=n,
                        supplied_hash=batch_hash,
                    )
                    _validate_live_confirmation(confirm, n, batch_hash, computed_hash)
                except LiveConfirmMismatch:
                    # A valid-looking nonce tied to a changed batch / n is
                    # single-use even when the start is rejected.
                    _burn_live_nonce(plan_nonce)
                    raise
            # Prepare mode never talks to eBay, so it does not need OAuth.
            if mode == "full" and not ebay_oauth.oauth_connected(env):
                label = "live" if production else "sandbox"
                raise NotSignedIn(
                    f"NOT_SIGNED_IN: connect the {label} eBay account before uploading"
                )
            run_id = f"upload-{uuid.uuid4().hex[:12]}"
            if live_run:
                # A failed start-line append aborts before the worker (and any
                # eBay write) starts.
                _append_live_audit_strict(
                    {
                        "ts": _utc_now(),
                        "event": "start",
                        "run_id": run_id,
                        "mode": mode,
                        "env": env,
                        "n": n,
                        "batch_hash": computed_hash,
                        "cap": cap,
                        "who": "local",
                    }
                )
                # Consume only after every other check and the start line
                # succeeded; a rejected start keeps the nonce for a retry with
                # the same batch.
                consume_live_nonce(
                    plan_nonce,
                    mode=LIVE_MODE_UPLOAD,
                    env=env,
                    batch_hash=computed_hash,
                    n=n,
                )
            self.state = UploadJobState(
                run_id=run_id,
                target_env=env,
                started_at=_utc_now(),
                running=True,
                phase="starting",
                mode=mode,
                file=path.name,
                live=live_run,
                batch_hash=computed_hash,
                live_cap=cap,
                planned=n,
                rows=rows,
            )

        self._thread = threading.Thread(target=self._run, name="upload-items", daemon=True)
        self._thread.start()
        return self.status()

    def start_publish(
        self,
        asins: list[str],
        confirm: str | None = None,
        batch_hash: str | None = None,
        plan_nonce: str | None = None,
    ) -> dict[str, Any]:
        """Stage + publish already-prepared ASINs (sandbox or guarded live)."""
        env = config.ebay_env()
        production = env == "production"
        if production:
            missing = live_gate_missing(env)
            if missing:
                raise LiveUploadDisabled(live_gate_message(missing), missing)

        normalized: list[str] = []
        seen: set[str] = set()
        rows: list[UploadRow] = []
        line_no = 0
        for raw in asins or []:
            line_no += 1
            asin = normalize_asin(raw)
            if not asin:
                # Never let junk reach product_dir()/load_listing_state(): an
                # invalid value is reported as a row and nothing else.
                rows.append(
                    UploadRow(
                        line_no=line_no,
                        line=str(raw),
                        asin="",
                        state="not_prepared",
                        reason="invalid asin",
                    )
                )
                continue
            if asin in seen:
                continue
            seen.add(asin)
            normalized.append(asin)
            rows.append(
                UploadRow(line_no=line_no, line=asin, asin=asin, state="queued")
            )
        if not normalized:
            raise ValueError("asins required (non-empty list of valid ASINs)")

        n = len(normalized)
        cap = config.ebay_live_max_per_run() if production else 0
        computed_hash = ""
        if production:
            computed_hash = compute_batch_hash(
                mode=LIVE_MODE_PUBLISH,
                env=env,
                asins=normalized,
            )

        with self._lock:
            if self.state.running:
                raise UploadAlreadyRunning(self.state.run_id)
            if production:
                if n > cap:
                    raise LiveCapExceeded(n, cap)
                try:
                    validate_live_nonce(
                        plan_nonce,
                        mode=LIVE_MODE_PUBLISH,
                        env=env,
                        batch_hash=computed_hash,
                        n=n,
                        supplied_hash=batch_hash,
                    )
                    _validate_live_confirmation(confirm, n, batch_hash, computed_hash)
                except LiveConfirmMismatch:
                    _burn_live_nonce(plan_nonce)
                    raise
            if not ebay_oauth.oauth_connected(env):
                label = "live" if production else "sandbox"
                raise NotSignedIn(
                    f"NOT_SIGNED_IN: connect the {label} eBay account before publishing"
                )
            # Local-only pre-checks: never fetch Amazon for a known or
            # unprepared ASIN, and never fail the whole batch for it.
            for row in rows:
                if row.state != "queued":
                    continue
                existing = published_listing_state(row.asin, env)
                if existing is not None:
                    mark_row_listed(row, existing, row_state="skipped_existing")
                elif not draft_title_for(row.asin):
                    row.state = "not_prepared"
                    row.reason = "not prepared (no draft)"
            run_id = f"publish-{uuid.uuid4().hex[:12]}"
            if production:
                _append_live_audit_strict(
                    {
                        "ts": _utc_now(),
                        "event": "start",
                        "run_id": run_id,
                        "mode": "publish",
                        "env": env,
                        "n": n,
                        "batch_hash": computed_hash,
                        "cap": cap,
                        "who": "local",
                    }
                )
                consume_live_nonce(
                    plan_nonce,
                    mode=LIVE_MODE_PUBLISH,
                    env=env,
                    batch_hash=computed_hash,
                    n=n,
                )
            self.state = UploadJobState(
                run_id=run_id,
                target_env=env,
                started_at=_utc_now(),
                running=True,
                phase="starting",
                mode="publish",
                live=production,
                batch_hash=computed_hash,
                live_cap=cap,
                planned=n,
                rows=rows,
            )

        self._thread = threading.Thread(target=self._run, name="upload-items", daemon=True)
        self._thread.start()
        return self.status()

    def stop(self) -> dict[str, Any]:
        with self._lock:
            if self.state.running:
                self.state.stop_requested = True
                self.state.phase = "stopping"
        return self.status()

    # ------------------------------------------------------------------ worker

    def _run(self) -> None:
        # One frozen env for the whole worker lifetime.  While this operation
        # is in flight the target-switch endpoint refuses a change.
        with config.ebay_operation(self.state.target_env):
            self._run_worker()

    def _run_worker(self) -> None:
        # The pin covers the whole worker lifetime, including every helper
        # called by stage/publish.  try/finally guarantees release both after
        # a normal finish and after an unexpected crash.  A live run uses the
        # inverse pin: production only, and no sandbox host can be reached.
        live = self.state.live
        # Freeze the run's env for the whole worker lifetime: state files use
        # this captured value even if the target flips while a response is in
        # flight.
        config.set_run_env(self.state.target_env)
        if live:
            config.pin_production_for_live(True)
        else:
            config.pin_sandbox_for_upload(True)
        try:
            for pass_no in range(0, MAX_RETRY_PASSES + 1):
                if pass_no > 0:
                    with self._lock:
                        eligible = [
                            row for row in self.state.rows if self._is_retryable(row)
                        ]
                        if not eligible:
                            break
                        if self.state.stop_requested:
                            self.state.phase = "stopped"
                            return
                        self.state.retry_pass = pass_no
                        self.state.phase = "retrying"
                    # The pause is interruptible: Stop/target change ends the
                    # run within one small step instead of after the full wait.
                    if not self._retry_pause():
                        return
                    with self._lock:
                        self._requeue_retryable()
                if not self._run_pass():
                    return

            with self._lock:
                if self.state.stop_requested:
                    self.state.phase = "stopped"
                else:
                    self.state.phase = "finished"
        except Exception as exc:  # noqa: BLE001 - never leave a dead running flag
            with self._lock:
                self.state.error = _reason(exc)
                self.state.phase = "aborted"
        finally:
            try:
                # One audit line per row, including rows that were skipped or
                # never reached after Stop/abort.  A failed final append cannot
                # un-write anything, but it is still surfaced as a run error.
                self._audit_remaining()
            finally:
                if live:
                    config.pin_production_for_live(False)
                else:
                    config.pin_sandbox_for_upload(False)
                config.set_run_env(None)
                with self._lock:
                    # Also covers early exits via Stop / abort / target change:
                    # retryable rows that were already retried keep one
                    # consistent "after N attempts: ..." reason.
                    self._finalize_retry_reasons()
                    self.state.running = False

    def _run_pass(self) -> bool:
        """Run every queued row once; False means the whole run must end."""
        for row in self.state.rows:
            with self._lock:
                if self.state.stop_requested:
                    self.state.phase = "stopped"
                    return False
                if row.state != "queued":
                    continue
                self.state.phase = "running"
                row.started_at = _utc_now()
                row.finished_at = ""
                row.duration_sec = None
                row._started_monotonic = _monotonic()

            try:
                self._check_live_guard()
            except _LiveDisabled as exc:
                self._abort_live_disabled(row, exc)
                self._audit_row_quietly(row)
                return False
            except _TargetChanged as exc:
                self._abort_target_changed(row, reason=_reason(exc))
                self._audit_row_quietly(row)
                return False

            try:
                self._process_row(row)
            except _LiveDisabled as exc:
                self._abort_live_disabled(row, exc)
                self._audit_row_quietly(row)
                return False
            except _TargetChanged as exc:
                self._abort_target_changed(row, reason=_reason(exc))
                self._audit_row_quietly(row)
                return False
            except _AbortRun as exc:
                with self._lock:
                    row.state = "error"
                    row.reason = _reason(exc)
                    self._stamp_finished(row)
                    self.state.error = _reason(exc)
                    self.state.phase = "aborted"
                self._audit_row_quietly(row)
                return False
            except LiveAuditError as exc:
                # No eBay call happened for this row: the intent append failed
                # first, so the run stops exactly like a failed result append.
                self._abort_audit(row, exc)
                return False
            retry_may_follow = (
                self._is_retryable(row)
                and self.state.retry_pass < MAX_RETRY_PASSES
            )
            if self.state.live and not retry_may_follow:
                try:
                    self._audit_row(row)
                except LiveAuditError as exc:
                    self._abort_audit(row, exc)
                    return False
        return True

    @staticmethod
    def _is_retryable(row: UploadRow) -> bool:
        if row.state != "error":
            return False
        text = str(row.reason).strip().upper()
        if not text.startswith(RETRYABLE_ERROR_PREFIX):
            return False
        # ``AMAZON_UNREACHABLE_NOT...`` is a different error and must not be
        # treated as a transient connection failure.
        return len(text) == len(RETRYABLE_ERROR_PREFIX) or (
            text[len(RETRYABLE_ERROR_PREFIX)] == ":"
        )

    def _requeue_retryable(self) -> None:
        """Reset every transient row to queued for another pass (lock held)."""
        for row in self.state.rows:
            if not self._is_retryable(row):
                continue
            row.attempts += 1
            row.state = "queued"
            row.reason = ""
            row.started_at = ""
            row.finished_at = ""
            row.duration_sec = None
            row._started_monotonic = None

    def _retry_pause(self) -> bool:
        """Sleep before a retry pass in small slices; False ends the run."""
        remaining = max(0.0, float(RETRY_PASS_PAUSE_SEC))
        while remaining > 0:
            if self.state.stop_requested:
                with self._lock:
                    self.state.phase = "stopped"
                return False
            if not self._retry_pause_guard_ok():
                return False
            step = min(_RETRY_PAUSE_STEP_SEC, remaining)
            time.sleep(step)
            remaining -= step
        if self.state.stop_requested:
            with self._lock:
                self.state.phase = "stopped"
            return False
        return self._retry_pause_guard_ok()

    def _retry_pause_guard_ok(self) -> bool:
        try:
            self._check_live_guard()
        except _LiveDisabled as exc:
            with self._lock:
                self.state.error = _reason(exc)
                self.state.phase = "aborted_live_disabled"
            return False
        except _TargetChanged as exc:
            with self._lock:
                self.state.error = _reason(exc)
                self.state.phase = "aborted_target_changed"
            return False
        return True

    def _finalize_retry_reasons(self) -> None:
        """Mark exhausted transient failures with their total attempt count."""
        for row in self.state.rows:
            if row.attempts > 1 and self._is_retryable(row):
                row.reason = f"after {row.attempts} attempts: {row.reason}"

    def _abort_target_changed(
        self, row: UploadRow, *, reason: str = ""
    ) -> None:
        if row.state == "published":
            # The listing was already created; keep the ids and say exactly
            # what happened.  The row still ends in ``error``.
            message = (
                f"published in {self.state.target_env}; "
                "target changed after response"
            )
        else:
            message = reason or "eBay target changed during the run"
            if not message.startswith("aborted_target_changed"):
                message = f"aborted_target_changed: {message}"
        with self._lock:
            # A row that only got as far as drafting/staging is not a success:
            # the batch aborted around it, so surface it as an error exactly
            # like the systemic-abort path does.
            row.state = "error"
            row.reason = message
            self._stamp_finished(row)
            self.state.error = row.reason
            self.state.phase = "aborted_target_changed"

    def _abort_live_disabled(self, row: UploadRow, exc: BaseException) -> None:
        message = _reason(exc)
        if not message.startswith("aborted_live_disabled"):
            message = f"aborted_live_disabled: {message}"
        with self._lock:
            row.state = "error"
            row.reason = message
            self._stamp_finished(row)
            self.state.error = message
            self.state.phase = "aborted_live_disabled"

    def _abort_audit(self, row: UploadRow, exc: BaseException) -> None:
        message = _reason(exc)
        with self._lock:
            self.state.error = message
            self.state.phase = "aborted_audit_failed"
            if row.state in ("queued", "fetching", "evaluated", "drafted", "staged"):
                row.state = "error"
                row.reason = message
                self._stamp_finished(row)

    def _check_live_guard(self) -> None:
        """Target + live-gate check, re-read before every row and write."""
        if config.ebay_env() != self.state.target_env:
            raise _TargetChanged("eBay target changed during the run")
        if not self.state.live:
            return
        if not config.ebay_live_upload_enabled():
            raise _LiveDisabled(
                "aborted_live_disabled: EBAY_LIVE_UPLOAD_ENABLED is false"
            )
        missing = [
            name
            for name in live_gate_missing(self.state.target_env)
            if name != LIVE_MISSING_FLAG
        ]
        if missing:
            raise _LiveDisabled(
                "aborted_live_disabled: missing " + ", ".join(missing)
            )
        try:
            tokens = ebay_oauth.load_tokens_for("production")
        except Exception:  # noqa: BLE001 - unreadable token means no live write
            tokens = {}
        token_env = str(tokens.get("env") or "").strip()
        if token_env and token_env != "production":
            raise _TargetChanged("token env mismatch during live run")

    def _check_target(self) -> None:
        self._check_live_guard()

    def _check_target_after_response(self) -> None:
        """The response belongs to the start env even if the target flipped."""
        if config.ebay_env() != self.state.target_env:
            raise _TargetChanged("target changed after response")

    def _audit_intent(self, row: UploadRow) -> None:
        """Append the pre-write intent line; a failure aborts before any call."""
        if not self.state.live or row._intent_audited:
            return
        _append_live_audit_strict(
            {
                "ts": _utc_now(),
                "event": "intent",
                "run_id": self.state.run_id,
                "asin": row.asin,
                "sku": ebay_listing.sku_for_asin(row.asin) if row.asin else "",
                "price": row.price,
                "mode": self.state.mode,
            }
        )
        row._intent_audited = True

    def _audit_row(self, row: UploadRow) -> None:
        if not self.state.live or row._audited:
            return
        _append_live_audit_strict(
            {
                "ts": _utc_now(),
                "event": "result",
                "run_id": self.state.run_id,
                "asin": row.asin,
                "sku": ebay_listing.sku_for_asin(row.asin) if row.asin else "",
                "state": row.state,
                "offer_id": row.offer_id,
                "listing_id": row.listing_id,
                "price": row.price,
                "reason": row.reason,
                "mode": self.state.mode,
            }
        )
        row._audited = True

    def _audit_row_quietly(self, row: UploadRow) -> None:
        try:
            self._audit_row(row)
        except LiveAuditError:
            # The run is already aborting; the original abort reason wins.
            pass

    def _audit_remaining(self) -> None:
        if not self.state.live:
            return
        for row in list(self.state.rows):
            if row._audited:
                continue
            try:
                self._audit_row(row)
            except LiveAuditError as exc:
                with self._lock:
                    self.state.error = _reason(exc)
                    self.state.phase = "aborted_audit_failed"
                return

    def _stamp_finished(self, row: UploadRow) -> None:
        """Stamp a monotonic duration once, when the row becomes terminal.

        Caller must hold ``self._lock``.  Rows that never started (parser
        rejects, duplicates) keep ``duration_sec`` as ``None``.
        """
        if row.finished_at or row._started_monotonic is None:
            return
        row.duration_sec = max(
            0.0, round(_monotonic() - row._started_monotonic, 3)
        )
        row.finished_at = _utc_now()

    def _fetch_offer(self, asin: str) -> OfferIn:
        """Fetch the PDP and reject variation parents exactly like generate_draft.

        ``fetch_variation_offers`` already executes every lookup through the
        existing reliable-fetch policy (pacing, bounded retry, failure cap).
        """
        offers = fetch_variation_offers(asin)
        requested = (asin or "").strip().upper()
        child_asins = {(offer.asin or "").strip().upper() for offer in offers}
        # ``fetch_variation_offers`` returns the child offers when Amazon
        # exposes variations.  If the requested ASIN is not one of them it is
        # the parent hub — reject it even when only a single child survived.
        if not offers or requested not in child_asins:
            raise VariationParentError("variation_parent")
        # A variation page whose child fetches all failed also falls back to
        # the parent snapshot.  The scan metadata makes that distinguishable
        # from a plain product with one matching offer.
        if getattr(offers, "reported_variations", False) and not getattr(
            offers, "children_fetched", 0
        ):
            raise VariationParentError("variation_parent")
        return next(
            (offer for offer in offers if (offer.asin or "").strip().upper() == requested),
            offers[0],
        )

    def _process_row(self, row: UploadRow) -> None:
        if self.state.mode == "publish":
            self._process_publish_row(row)
            return

        asin = row.asin

        # Mark known ASINs before the expensive Amazon work starts.  This is a
        # local state-file read only: no fetch/evaluate/draft/stage/publish.
        existing = published_listing_state(asin, self.state.target_env)
        if existing is not None:
            with self._lock:
                mark_row_listed(row, existing, row_state="skipped_existing")
                self._stamp_finished(row)
            return

        if self.state.mode == "prepare" and already_prepared(
            asin, self.state.target_env
        ):
            # A previous prepare run already built the draft.  Skip before any
            # Amazon fetch or LLM call.
            with self._lock:
                row.state = "skipped_existing"
                row.reason = PREPARED_REASON
                self._stamp_finished(row)
            return

        with self._lock:
            row.state = "fetching"
            row.reason = ""

        try:
            offer = self._fetch_offer(asin)
        except VariationParentError:
            # The PDP is a hub for sellable children; never stage/publish it.
            self._finish(row, "rejected", "variation_parent")
            return
        except Exception as exc:  # noqa: BLE001 - classified below
            if _is_not_found(exc):
                self._finish(row, "not_found", _reason(exc) or "ASIN_NOT_FOUND")
                return
            if _is_systemic(exc):
                raise _AbortRun(_reason(exc)) from exc
            self._finish(row, "error", _reason(exc))
            return

        # Parent detection happens in _fetch_offer() from the full offer list.
        # Do not reject a genuine child merely because it carries the parent's
        # ASIN in ``offer.parent_asin``.
        try:
            evaluation = run_evaluate(
                EvaluateRequest(asin_or_url=asin, offer=offer, save=True),
                persist="always",
            )
        except Exception as exc:  # noqa: BLE001
            self._finish(row, "error", _reason(exc))
            return

        if not evaluation.passed:
            reasons = list(evaluation.hard_reject_reasons)
            reasons.extend(str(x) for x in (evaluation.margin.get("fail_reasons") or []))
            self._finish(row, "rejected", "; ".join(reasons) or "margin gate failed")
            return

        with self._lock:
            row.state = "evaluated"
            row.price = ebay_listing.canonical_price(evaluation.ebay_price)

        self._check_target()
        # Final re-check: a previous row in this run (or another process) may
        # have published the same ASIN while we were fetching.
        existing = published_listing_state(asin, self.state.target_env)
        if existing is not None:
            with self._lock:
                mark_row_listed(row, existing, row_state="skipped_existing")
                self._stamp_finished(row)
            return

        try:
            generated = generate_draft(
                asin,
                ebay_price=ebay_listing.canonical_price(evaluation.ebay_price),
                amazon_total=float(offer.amazon_total),
                title=offer.title,
                offer=offer,
                evaluate=False,
            )
        except VariationParentError as exc:
            self._finish(row, "rejected", _reason(exc))
            return
        except ListingGenerateError as exc:
            self._finish(row, "error", _reason(exc))
            return
        except Exception as exc:  # noqa: BLE001
            self._finish(row, "error", _reason(exc))
            return

        # The LLM sometimes drops the Amazon variation label from the title.
        # Fix that deterministically here (no second LLM call): stage_unpublished
        # still keeps its guard, it just receives a corrected draft_patch.
        draft_title = ""
        if isinstance(generated, dict):
            draft_body = generated.get("draft")
            if isinstance(draft_body, dict):
                draft_title = str(draft_body.get("title") or "")
        title_patch: dict[str, Any] | None = None
        variation_label = str(getattr(offer, "variation_label", "") or "").strip()
        if draft_title and variation_label:
            patched_title = title_with_variation(draft_title, variation_label)
            if patched_title != draft_title:
                title_patch = {"title": patched_title}

        with self._lock:
            row.state = "drafted"

        if self.state.mode == "prepare":
            # Persist the (patched) draft and stop: no stage_unpublished, no
            # publish_offer, no eBay/OAuth traffic at all.
            self._save_prepared_draft(row, generated, title_patch)
            return

        self._check_target()
        # Audit intent before the first eBay call of this row.  A failed
        # append raises here, so the row makes no eBay call.
        self._audit_intent(row)
        stage_kwargs: dict[str, Any] = {}
        if self.state.live:
            # Bind the price that passed the margin gate.
            stage_kwargs["expected_price"] = row.price
        try:
            if title_patch is not None:
                staged = ebay_listing.stage_unpublished(
                    asin, draft_patch=title_patch, **stage_kwargs
                )
            else:
                staged = ebay_listing.stage_unpublished(asin, **stage_kwargs)
        except Exception as exc:  # noqa: BLE001
            if _is_live_write_blocked(exc) or config.ebay_env() != self.state.target_env:
                raise _TargetChanged(_reason(exc)) from exc
            self._finish(row, "error", _reason(exc))
            return
        with self._lock:
            row.offer_id = str(staged.get("offer_id") or "")
            # The audit/result line records the price actually staged.
            staged_price = _state_price(staged)
            if staged_price is not None:
                row.price = staged_price
            row.state = "staged"
        self._check_target_after_response()

        self._check_target()
        try:
            published = ebay_listing.publish_offer(asin)
        except Exception as exc:  # noqa: BLE001
            if _is_live_write_blocked(exc) or config.ebay_env() != self.state.target_env:
                raise _TargetChanged(_reason(exc)) from exc
            self._finish(row, "error", _reason(exc))
            return
        with self._lock:
            row.offer_id = str(published.get("offer_id") or row.offer_id)
            row.listing_id = str(published.get("listing_id") or "")
            row.item_url = str(published.get("item_url") or "")
            published_price = _state_price(published)
            if published_price is not None:
                row.price = published_price
            row.state = "published"
            self._stamp_finished(row)
        self._check_target_after_response()

    def _save_prepared_draft(
        self, row: UploadRow, generated: Any, title_patch: dict[str, Any] | None
    ) -> None:
        """Store the generated draft (with the deterministic title patch)."""
        draft = generated.get("draft") if isinstance(generated, dict) else None
        if not isinstance(draft, dict) or not str(draft.get("title") or "").strip():
            self._finish(row, "error", "draft missing title")
            return
        stored = dict(draft)
        if title_patch:
            stored.update(title_patch)
        try:
            save_listing_draft(row.asin, stored)
        except Exception as exc:  # noqa: BLE001
            self._finish(row, "error", _reason(exc))
            return
        self._finish(row, "prepared", "")

    def _process_publish_row(self, row: UploadRow) -> None:
        """Re-check the price, then stage + publish an already-prepared ASIN."""
        asin = row.asin

        existing = published_listing_state(asin, self.state.target_env)
        if existing is not None:
            with self._lock:
                mark_row_listed(row, existing, row_state="skipped_existing")
                self._stamp_finished(row)
            return

        if not draft_title_for(asin):
            with self._lock:
                row.state = "not_prepared"
                row.reason = "not prepared (no draft)"
                self._stamp_finished(row)
            return

        candidate = get_candidate_by_asin(asin) or {}
        stored_price = candidate.get("ebay_price")
        prepared_price = (
            ebay_listing.canonical_price(stored_price)
            if stored_price is not None
            else None
        )

        with self._lock:
            row.state = "fetching"
            row.reason = ""

        try:
            offer = self._fetch_offer(asin)
        except VariationParentError:
            self._finish(row, "rejected", "variation_parent")
            return
        except Exception as exc:  # noqa: BLE001 - classified below
            if _is_not_found(exc):
                self._finish(row, "not_found", _reason(exc) or "ASIN_NOT_FOUND")
                return
            if _is_systemic(exc):
                raise _AbortRun(_reason(exc)) from exc
            self._finish(row, "error", _reason(exc))
            return

        # Price re-check: never publish on a stale margin.  The candidate's
        # prepared sale price is authoritative; run_evaluate() must not quietly
        # replace it with a higher suggestion.  The draft itself is not
        # regenerated (that already happened in prepare mode).
        try:
            evaluation = run_evaluate(
                EvaluateRequest(
                    asin_or_url=asin,
                    offer=offer,
                    ebay_price=prepared_price,
                    save=True,
                ),
                persist="always",
            )
        except Exception as exc:  # noqa: BLE001
            self._finish(row, "error", _reason(exc))
            return

        if not evaluation.passed:
            reasons = list(evaluation.hard_reject_reasons)
            reasons.extend(str(x) for x in (evaluation.margin.get("fail_reasons") or []))
            if prepared_price is not None and evaluation.margin.get("fail_reasons"):
                reason = (
                    f"price changed: prepared {prepared_price:.2f} EUR no longer "
                    f"passes the margin gate (Amazon now {float(offer.amazon_total):.2f})"
                )
                if reasons:
                    reason = f"{reason}: {'; '.join(reasons)}"
            else:
                reason = "; ".join(reasons) or "margin gate failed"
            self._finish(row, "rejected", reason)
            return

        with self._lock:
            row.state = "evaluated"
            row.price = (
                prepared_price
                if prepared_price is not None
                else ebay_listing.canonical_price(evaluation.ebay_price)
            )

        self._check_target()
        existing = published_listing_state(asin, self.state.target_env)
        if existing is not None:
            with self._lock:
                mark_row_listed(row, existing, row_state="skipped_existing")
                self._stamp_finished(row)
            return

        self._audit_intent(row)
        stage_kwargs: dict[str, Any] = {}
        if self.state.live:
            stage_kwargs["expected_price"] = row.price
        try:
            staged = ebay_listing.stage_unpublished(asin, **stage_kwargs)
        except Exception as exc:  # noqa: BLE001
            if _is_live_write_blocked(exc) or config.ebay_env() != self.state.target_env:
                raise _TargetChanged(_reason(exc)) from exc
            self._finish(row, "error", _reason(exc))
            return
        with self._lock:
            row.offer_id = str(staged.get("offer_id") or "")
            staged_price = _state_price(staged)
            if staged_price is not None:
                row.price = staged_price
            row.state = "staged"
        self._check_target_after_response()

        self._check_target()
        try:
            published = ebay_listing.publish_offer(asin)
        except Exception as exc:  # noqa: BLE001
            if _is_live_write_blocked(exc) or config.ebay_env() != self.state.target_env:
                raise _TargetChanged(_reason(exc)) from exc
            self._finish(row, "error", _reason(exc))
            return
        with self._lock:
            row.offer_id = str(published.get("offer_id") or row.offer_id)
            row.listing_id = str(published.get("listing_id") or "")
            row.item_url = str(published.get("item_url") or "")
            published_price = _state_price(published)
            if published_price is not None:
                row.price = published_price
            row.state = "published"
            self._stamp_finished(row)
        self._check_target_after_response()

    def _finish(self, row: UploadRow, state: str, reason: str) -> None:
        with self._lock:
            row.state = state
            row.reason = reason
            self._stamp_finished(row)


UPLOAD_JOB = UploadJobManager()
