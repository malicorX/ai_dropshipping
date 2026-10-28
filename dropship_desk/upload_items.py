"""Read upload_items.txt and publish each Amazon link as an eBay listing.

The file is the operator's batch queue: one Amazon.de link (or bare ASIN) per
line.  The job is intentionally sequential and single-flight, and it refuses to
run in production until live writes are explicitly enabled by the operator.
"""

from __future__ import annotations

import os
import re
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
    """Production is refused before any network call."""


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
    started_at: str = ""
    finished_at: str = ""
    duration_sec: float | None = None
    attempts: int = 1
    _started_monotonic: float | None = field(
        default=None, repr=False, compare=False
    )

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


def published_listing_state(asin: str, env: str) -> dict[str, Any] | None:
    """Return the saved listing when ``asin`` is already published for ``env``.

    This is a local, file-only read (no network).  Sandbox and production keep
    separate state files; the stored ``env`` is checked as a second guard for
    legacy records that predate the per-env file split.
    """
    target = (env or "").strip()
    try:
        state = ebay_listing.load_listing_state(asin)
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


def read_upload_file(path: str | Path | None = None) -> list[UploadRow]:
    """Parse the upload file, deduping ASINs without dropping the original line."""
    target = Path(path) if path is not None else upload_items_path()
    if not target.is_file():
        raise UploadFileMissing(target)

    rows: list[UploadRow] = []
    first_line_by_asin: dict[str, int] = {}
    text = target.read_text(encoding="utf-8-sig", errors="replace")
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

    def start(self, mode: str = "full", file: str | None = None) -> dict[str, Any]:
        mode = str(mode or "full").strip().lower()
        if mode not in ("full", "prepare"):
            raise ValueError(f"unknown upload mode {mode!r} (use 'full' or 'prepare')")
        env = config.ebay_env()
        if env == "production":
            raise LiveUploadDisabled(
                "LIVE_UPLOAD_DISABLED: live eBay uploads are disabled by the operator"
            )
        # Trust boundary: an explicit name is validated before any file read.
        path = resolve_upload_file(file)

        with self._lock:
            if self.state.running:
                raise UploadAlreadyRunning(self.state.run_id)
            rows = read_upload_file(path)
            # Prepare mode never talks to eBay, so it does not need OAuth.
            if mode == "full" and not ebay_oauth.oauth_connected(env):
                raise NotSignedIn(
                    "NOT_SIGNED_IN: connect the sandbox eBay account before uploading"
                )
            run_id = f"upload-{uuid.uuid4().hex[:12]}"
            self.state = UploadJobState(
                run_id=run_id,
                target_env=env,
                started_at=_utc_now(),
                running=True,
                phase="starting",
                mode=mode,
                file=path.name,
                rows=rows,
            )

        self._thread = threading.Thread(target=self._run, name="upload-items", daemon=True)
        self._thread.start()
        return self.status()

    def start_publish(self, asins: list[str]) -> dict[str, Any]:
        """Stage + publish already-prepared ASINs (sandbox only)."""
        env = config.ebay_env()
        if env == "production":
            raise LiveUploadDisabled(
                "LIVE_UPLOAD_DISABLED: live eBay uploads are disabled by the operator"
            )

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

        with self._lock:
            if self.state.running:
                raise UploadAlreadyRunning(self.state.run_id)
            if not ebay_oauth.oauth_connected(env):
                raise NotSignedIn(
                    "NOT_SIGNED_IN: connect the sandbox eBay account before publishing"
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
            self.state = UploadJobState(
                run_id=run_id,
                target_env=env,
                started_at=_utc_now(),
                running=True,
                phase="starting",
                mode="publish",
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
        # The pin covers the whole worker lifetime, including every helper
        # called by stage/publish.  try/finally guarantees release both after
        # a normal finish and after an unexpected crash.
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
            config.pin_sandbox_for_upload(False)
            with self._lock:
                # Also covers early exits via Stop / abort / target change:
                # retryable rows that were already retried keep one consistent
                # "after N attempts: ..." reason.
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

            if config.ebay_env() != self.state.target_env:
                self._abort_target_changed(row)
                return False

            try:
                self._process_row(row)
            except _TargetChanged:
                self._abort_target_changed(row)
                return False
            except _AbortRun as exc:
                with self._lock:
                    row.state = "error"
                    row.reason = _reason(exc)
                    self._stamp_finished(row)
                    self.state.error = _reason(exc)
                    self.state.phase = "aborted"
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
            if config.ebay_env() != self.state.target_env:
                with self._lock:
                    self.state.error = (
                        "aborted_target_changed: eBay target changed during the run"
                    )
                    self.state.phase = "aborted_target_changed"
                return False
            step = min(_RETRY_PAUSE_STEP_SEC, remaining)
            time.sleep(step)
            remaining -= step
        if self.state.stop_requested:
            with self._lock:
                self.state.phase = "stopped"
            return False
        if config.ebay_env() != self.state.target_env:
            with self._lock:
                self.state.error = (
                    "aborted_target_changed: eBay target changed during the run"
                )
                self.state.phase = "aborted_target_changed"
            return False
        return True

    def _finalize_retry_reasons(self) -> None:
        """Mark exhausted transient failures with their total attempt count."""
        for row in self.state.rows:
            if row.attempts > 1 and self._is_retryable(row):
                row.reason = f"after {row.attempts} attempts: {row.reason}"

    def _abort_target_changed(self, row: UploadRow) -> None:
        with self._lock:
            # A row that only got as far as drafting/staging is not a success:
            # the batch aborted around it, so surface it as an error exactly
            # like the systemic-abort path does.
            row.state = "error"
            row.reason = "aborted_target_changed: eBay target changed during the run"
            self._stamp_finished(row)
            self.state.error = row.reason
            self.state.phase = "aborted_target_changed"

    def _check_target(self) -> None:
        if config.ebay_env() != self.state.target_env:
            raise _TargetChanged("eBay target changed during the run")

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
                ebay_price=float(evaluation.ebay_price),
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
        try:
            if title_patch is not None:
                staged = ebay_listing.stage_unpublished(asin, draft_patch=title_patch)
            else:
                staged = ebay_listing.stage_unpublished(asin)
        except Exception as exc:  # noqa: BLE001
            if _is_live_write_blocked(exc) or config.ebay_env() != self.state.target_env:
                raise _TargetChanged(_reason(exc)) from exc
            self._finish(row, "error", _reason(exc))
            return
        with self._lock:
            row.offer_id = str(staged.get("offer_id") or "")
            row.state = "staged"

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
            row.state = "published"
            self._stamp_finished(row)

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
        prepared_price = float(stored_price) if stored_price is not None else None

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

        self._check_target()
        existing = published_listing_state(asin, self.state.target_env)
        if existing is not None:
            with self._lock:
                mark_row_listed(row, existing, row_state="skipped_existing")
                self._stamp_finished(row)
            return

        try:
            staged = ebay_listing.stage_unpublished(asin)
        except Exception as exc:  # noqa: BLE001
            if _is_live_write_blocked(exc) or config.ebay_env() != self.state.target_env:
                raise _TargetChanged(_reason(exc)) from exc
            self._finish(row, "error", _reason(exc))
            return
        with self._lock:
            row.offer_id = str(staged.get("offer_id") or "")
            row.state = "staged"

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
            row.state = "published"
            self._stamp_finished(row)

    def _finish(self, row: UploadRow, state: str, reason: str) -> None:
        with self._lock:
            row.state = state
            row.reason = reason
            self._stamp_finished(row)


UPLOAD_JOB = UploadJobManager()
