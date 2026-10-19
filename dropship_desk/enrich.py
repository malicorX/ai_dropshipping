"""Enrich candidates that lack stars/reviews via Amazon PDP (slow, paced)."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from dropship_desk.amazon.product import fetch_variation_offers
from dropship_desk.db import list_candidates
from dropship_desk.variation_expand import persist_variation_offers

ProgressCb = Callable[[dict[str, Any]], None]


def _needs_amazon_refresh(row: dict[str, Any]) -> bool:
    if row.get("status") in ("listed", "ebay_unpublished"):
        return False
    offer = row.get("offer") or {}
    if offer.get("stars") is None or offer.get("reviews") is None:
        return True
    if offer.get("variation_label"):
        return False
    if offer.get("price_source") == "serp":
        return True
    note = str(offer.get("note") or "").lower()
    return "variation" in note


def _missing_rows(*, status: str | None, limit: int) -> list[dict[str, Any]]:
    rows = list_candidates(limit=200, status=status)
    missing = [r for r in rows if _needs_amazon_refresh(r)]
    return missing[:limit]


def enrich_missing(
    *,
    limit: int = 30,
    pause_sec: float = 4.0,
    status: str | None = "ready",
    on_progress: ProgressCb | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    missing = _missing_rows(status=status, limit=limit)
    targeted = len(missing)

    updated = 0
    errors: list[str] = []
    details: list[dict[str, Any]] = []

    def emit(**extra: Any) -> None:
        if on_progress is None:
            return
        on_progress(
            {
                "targeted": targeted,
                "done": updated + len(errors),
                "updated": updated,
                "errors": list(errors),
                **extra,
            }
        )

    emit(current_asin=None, phase="start")

    for i, row in enumerate(missing):
        if should_stop and should_stop():
            emit(current_asin=None, phase="stopped")
            break

        asin = row["asin"]
        emit(current_asin=asin, phase="fetch", index=i + 1)
        try:
            offers = fetch_variation_offers(asin)
            expanded = persist_variation_offers(asin, offers, persist="always")
            primary = offers[0]
            if expanded.results:
                primary_eval = next(
                    (r for r in expanded.results if r.asin == asin), expanded.results[0]
                )
                primary = primary_eval.offer
            updated += 1
            details.append(
                {
                    "asin": primary.asin,
                    "stars": primary.stars,
                    "reviews": primary.reviews,
                    "amazon_total": primary.amazon_total,
                    "ebay_price": (
                        expanded.results[0].ebay_price if expanded.results else None
                    ),
                    "expanded": expanded.expanded,
                    "children": expanded.child_asins,
                }
            )
        except Exception as e:  # noqa: BLE001
            errors.append(f"{asin}: {e}")

        emit(current_asin=asin, phase="item_done", index=i + 1)

        if i + 1 < len(missing):
            if should_stop and should_stop():
                emit(current_asin=None, phase="stopped")
                break
            time.sleep(pause_sec)

    result = {
        "targeted": targeted,
        "updated": updated,
        "errors": errors[:10],
        "details": details,
        "done": updated + len(errors),
    }
    emit(current_asin=None, phase="finished")
    return result


@dataclass
class EnrichJobState:
    running: bool = False
    stop_requested: bool = False
    status_filter: str | None = "ready"
    targeted: int = 0
    done: int = 0
    updated: int = 0
    index: int = 0
    current_asin: str | None = None
    phase: str = "idle"
    error: str | None = None
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "stop_requested": self.stop_requested,
            "status_filter": self.status_filter,
            "targeted": self.targeted,
            "done": self.done,
            "updated": self.updated,
            "index": self.index,
            "current_asin": self.current_asin,
            "phase": self.phase,
            "error": self.error,
            "errors": self.errors[-10:],
        }


class EnrichJobManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.state = EnrichJobState()
        self._thread: threading.Thread | None = None

    def status(self) -> dict[str, Any]:
        with self._lock:
            return self.state.to_dict()

    def start(self, *, limit: int = 20, status: str | None = "ready", pause_sec: float = 4.0) -> dict[str, Any]:
        with self._lock:
            if self.state.running:
                raise RuntimeError("Enrich already running")
            self.state = EnrichJobState(
                running=True,
                status_filter=status,
                phase="starting",
            )

        def run() -> None:
            try:
                def on_progress(p: dict[str, Any]) -> None:
                    with self._lock:
                        self.state.targeted = int(p.get("targeted") or 0)
                        self.state.done = int(p.get("done") or 0)
                        self.state.updated = int(p.get("updated") or 0)
                        self.state.index = int(p.get("index") or self.state.done)
                        self.state.current_asin = p.get("current_asin")
                        self.state.phase = str(p.get("phase") or self.state.phase)
                        self.state.errors = list(p.get("errors") or [])

                enrich_missing(
                    limit=limit,
                    pause_sec=pause_sec,
                    status=status,
                    on_progress=on_progress,
                    should_stop=lambda: self.state.stop_requested,
                )
            except Exception as e:  # noqa: BLE001
                with self._lock:
                    self.state.error = str(e)
            finally:
                with self._lock:
                    self.state.running = False
                    self.state.current_asin = None
                    if self.state.phase not in ("finished", "stopped"):
                        self.state.phase = "finished" if not self.state.stop_requested else "stopped"

        self._thread = threading.Thread(target=run, name="enrich-missing", daemon=True)
        self._thread.start()
        return self.status()

    def stop(self) -> dict[str, Any]:
        with self._lock:
            if self.state.running:
                self.state.stop_requested = True
                self.state.phase = "stopping"
        return self.status()


ENRICH_JOB = EnrichJobManager()
