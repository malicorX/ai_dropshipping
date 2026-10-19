"""Read upload_items.txt and publish each Amazon link as an eBay listing.

The file is the operator's batch queue: one Amazon.de link (or bare ASIN) per
line.  The job is intentionally sequential and single-flight, and it refuses to
run in production until live writes are explicitly enabled by the operator.
"""

from __future__ import annotations

import os
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dropship_desk import config
from dropship_desk.amazon.product import (
    AmazonUnreachable,
    AsinNotFound,
    ChromeNotFound,
    fetch_variation_offers,
)
from dropship_desk.asin import extract_asin
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
    "staged",
    "published",
    "skipped_existing",
    "not_found",
    "rejected",
    "error",
    "duplicate_in_file",
)
_TERMINAL_STATES = frozenset(ROW_STATES) - {"queued", "fetching"}


class UploadFileMissing(FileNotFoundError):
    """The configured upload file does not exist."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        super().__init__(f"UPLOAD_FILE_MISSING: {self.path}")


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
        }


def upload_items_path() -> Path:
    """The operator file, honouring the UPLOAD_ITEMS_FILE override."""
    override = (os.environ.get("UPLOAD_ITEMS_FILE") or "").strip()
    if override:
        return Path(override)
    return config.RUNTIME_ROOT / "upload_items" / "upload_items.txt"


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


@dataclass
class UploadJobState:
    run_id: str = ""
    target_env: str = ""
    started_at: str = ""
    running: bool = False
    stop_requested: bool = False
    phase: str = "idle"
    error: str = ""
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
            "error": self.error,
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

    def start(self) -> dict[str, Any]:
        env = config.ebay_env()
        if env == "production":
            raise LiveUploadDisabled(
                "LIVE_UPLOAD_DISABLED: live eBay uploads are disabled by the operator"
            )

        with self._lock:
            if self.state.running:
                raise UploadAlreadyRunning(self.state.run_id)
            rows = read_upload_file()
            if not ebay_oauth.oauth_connected(env):
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
            for row in self.state.rows:
                with self._lock:
                    if self.state.stop_requested:
                        self.state.phase = "stopped"
                        return
                    if row.state != "queued":
                        continue
                    self.state.phase = "running"

                if config.ebay_env() != self.state.target_env:
                    self._abort_target_changed(row)
                    return

                try:
                    self._process_row(row)
                except _TargetChanged:
                    self._abort_target_changed(row)
                    return
                except _AbortRun as exc:
                    with self._lock:
                        row.state = "error"
                        row.reason = _reason(exc)
                        self.state.error = _reason(exc)
                        self.state.phase = "aborted"
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
                self.state.running = False

    def _abort_target_changed(self, row: UploadRow) -> None:
        with self._lock:
            if row.state not in _TERMINAL_STATES:
                row.state = "error"
            row.reason = "aborted_target_changed: eBay target changed during the run"
            self.state.error = row.reason
            self.state.phase = "aborted_target_changed"

    def _check_target(self) -> None:
        if config.ebay_env() != self.state.target_env:
            raise _TargetChanged("eBay target changed during the run")

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
        asin = row.asin
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
        existing = ebay_listing.load_listing_state(asin)
        if str(existing.get("status") or "") == "published":
            with self._lock:
                row.state = "skipped_existing"
                row.reason = "already published for this eBay environment"
                row.offer_id = str(existing.get("offer_id") or "")
                row.listing_id = str(existing.get("listing_id") or "")
                row.item_url = str(existing.get("item_url") or "")
            return

        try:
            generate_draft(
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

        with self._lock:
            row.state = "drafted"

        self._check_target()
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

    def _finish(self, row: UploadRow, state: str, reason: str) -> None:
        with self._lock:
            row.state = state
            row.reason = reason


UPLOAD_JOB = UploadJobManager()
