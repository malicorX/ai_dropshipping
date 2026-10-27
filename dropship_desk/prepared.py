"""Overview of prepared-but-not-live items.

"Prepared" means: a listing draft with a title exists and the ASIN is not
published for the current eBay target.  The overview is a local, read-only
view: state files and SQLite only, no Amazon and no eBay traffic.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from dropship_desk import config
from dropship_desk.db import list_candidates
from dropship_desk.ebay import listing as ebay_listing

# Effectively unbounded: the overview must show every prepared candidate.
_CANDIDATE_LIMIT = 1_000_000


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _listing_state(asin: str, env: str) -> dict[str, Any]:
    """The current-env listing state, ignoring records for another target."""
    try:
        state = ebay_listing.load_listing_state(asin)
    except OSError:
        return {}
    if not isinstance(state, dict) or not state:
        return {}
    state_env = str(state.get("env") or "").strip()
    if state_env and env and state_env != env:
        return {}
    return state


def _age_days(prepared_at: str, now: datetime) -> float:
    raw = str(prepared_at or "").strip()
    if not raw:
        return 0.0
    try:
        stamp = datetime.fromisoformat(raw)
    except ValueError:
        return 0.0
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    seconds = (now - stamp).total_seconds()
    return round(max(0.0, seconds) / 86_400, 2)


def _draft_title(draft: Any) -> str:
    if not isinstance(draft, dict):
        return ""
    return str(draft.get("title") or "").strip()


def list_prepared(
    env: str | None = None,
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Every drafted candidate whose current-env listing is not published."""
    target = (env or config.ebay_env() or "sandbox").strip()
    current = now or _now()
    items: list[dict[str, Any]] = []
    for row in list_candidates(limit=_CANDIDATE_LIMIT):
        title = _draft_title(row.get("listing_draft"))
        if not title:
            continue
        state = _listing_state(row["asin"], target)
        if str(state.get("status") or "") == "published":
            continue
        status = "unpublished" if str(state.get("status") or "") == "unpublished" else "none"
        prepared_at = str(row.get("updated_at") or "")
        margin = row.get("margin") if isinstance(row.get("margin"), dict) else {}
        items.append(
            {
                "asin": row["asin"],
                "title": title,
                "ebay_price": float(row.get("ebay_price") or 0.0),
                "amazon_total": float(row.get("amazon_total") or 0.0),
                "margin": margin,
                "prepared_at": prepared_at,
                "ebay_status": status,
                "offer_id": str(state.get("offer_id") or ""),
                "age_days": _age_days(prepared_at, current),
            }
        )
    items.sort(key=lambda item: item.get("prepared_at") or "", reverse=True)
    return items


def overview(env: str | None = None) -> dict[str, Any]:
    """Payload for GET /api/prepared (local only)."""
    target = (env or config.ebay_env() or "sandbox").strip()
    return {
        "target_env": target,
        "live_disabled": target == "production",
        "items": list_prepared(target),
    }
