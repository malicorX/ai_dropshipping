"""SQLite persistence for settings and candidates."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

from dropship_desk import config
from dropship_desk.models import MarginSettings

# Don't overwrite these with a fresh Find PASS/FAIL.
_PROTECTED_STATUSES = frozenset({"listed", "drafted"})


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    config.ensure_data_dir()
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asin TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                amazon_total REAL NOT NULL,
                ebay_price REAL NOT NULL,
                max_amazon_buy REAL NOT NULL,
                status TEXT NOT NULL,
                offer_json TEXT NOT NULL,
                margin_json TEXT NOT NULL,
                hard_reject_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        _dedupe_asins(conn)
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS candidates_asin_uq ON candidates(asin)"
        )
        cols = {
            row[1]
            for row in conn.execute("PRAGMA table_info(candidates)").fetchall()
        }
        if "listing_draft_json" not in cols:
            conn.execute(
                "ALTER TABLE candidates ADD COLUMN listing_draft_json TEXT NOT NULL DEFAULT ''"
            )


def _dedupe_asins(conn: sqlite3.Connection) -> None:
    """Keep newest row per ASIN before unique index."""
    dupes = conn.execute(
        """
        SELECT asin FROM candidates
        GROUP BY asin
        HAVING COUNT(*) > 1
        """
    ).fetchall()
    for row in dupes:
        asin = row["asin"]
        keep = conn.execute(
            """
            SELECT id FROM candidates WHERE asin = ?
            ORDER BY updated_at DESC, id DESC LIMIT 1
            """,
            (asin,),
        ).fetchone()
        if not keep:
            continue
        conn.execute(
            "DELETE FROM candidates WHERE asin = ? AND id != ?",
            (asin, keep["id"]),
        )


def get_margin_settings() -> MarginSettings:
    init_db()
    with connect() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?", ("margin",)
        ).fetchone()
    if not row:
        return MarginSettings()
    return MarginSettings.model_validate_json(row["value"])


def ensure_margin_policy() -> MarginSettings:
    """Migrate old factory default (20%) to 50%; leave custom Settings alone."""
    current = get_margin_settings()
    if abs(current.min_margin_pct - 0.20) < 1e-9:
        return set_margin_settings(
            current.model_copy(update={"min_margin_eur": 5.0, "min_margin_pct": 0.50})
        )
    return current


def set_margin_settings(settings: MarginSettings) -> MarginSettings:
    init_db()
    payload = settings.model_dump_json()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO settings(key, value) VALUES(?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            ("margin", payload),
        )
    return settings


def get_candidate_by_asin(asin: str) -> dict[str, Any] | None:
    init_db()
    with connect() as conn:
        row = conn.execute(
            """
            SELECT id, asin, title, amazon_total, ebay_price, max_amazon_buy,
                   status, offer_json, margin_json, hard_reject_json,
                   created_at, updated_at, listing_draft_json
            FROM candidates WHERE asin = ?
            """,
            (asin,),
        ).fetchone()
    if not row:
        return None
    return _row_to_dict(row)


def upsert_candidate(
    *,
    asin: str,
    title: str,
    amazon_total: float,
    ebay_price: float,
    max_amazon_buy: float,
    status: str,
    offer: dict[str, Any],
    margin: dict[str, Any],
    hard_reject: list[str],
) -> int:
    """Insert or refresh by ASIN. Protects listed/drafted workflow status."""
    init_db()
    now = _utc_now()
    asin = asin.strip().upper()
    with connect() as conn:
        existing = conn.execute(
            "SELECT id, status, created_at FROM candidates WHERE asin = ?",
            (asin,),
        ).fetchone()
        if existing:
            final_status = (
                existing["status"]
                if existing["status"] in _PROTECTED_STATUSES
                else status
            )
            conn.execute(
                """
                UPDATE candidates SET
                    title = ?, amazon_total = ?, ebay_price = ?, max_amazon_buy = ?,
                    status = ?, offer_json = ?, margin_json = ?, hard_reject_json = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    title,
                    amazon_total,
                    ebay_price,
                    max_amazon_buy,
                    final_status,
                    json.dumps(offer),
                    json.dumps(margin),
                    json.dumps(hard_reject),
                    now,
                    existing["id"],
                ),
            )
            return int(existing["id"])

        cur = conn.execute(
            """
            INSERT INTO candidates(
                asin, title, amazon_total, ebay_price, max_amazon_buy, status,
                offer_json, margin_json, hard_reject_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                asin,
                title,
                amazon_total,
                ebay_price,
                max_amazon_buy,
                status,
                json.dumps(offer),
                json.dumps(margin),
                json.dumps(hard_reject),
                now,
                now,
            ),
        )
        return int(cur.lastrowid)


# Back-compat name used by older call sites
insert_candidate = upsert_candidate


def list_candidates(
    limit: int = 200,
    *,
    status: str | None = None,
) -> list[dict[str, Any]]:
    init_db()
    with connect() as conn:
        if status:
            rows = conn.execute(
                """
                SELECT id, asin, title, amazon_total, ebay_price, max_amazon_buy,
                       status, offer_json, margin_json, hard_reject_json,
                       created_at, updated_at, listing_draft_json
                FROM candidates
                WHERE status = ?
                ORDER BY updated_at DESC, id DESC
                LIMIT ?
                """,
                (status, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, asin, title, amazon_total, ebay_price, max_amazon_buy,
                       status, offer_json, margin_json, hard_reject_json,
                       created_at, updated_at, listing_draft_json
                FROM candidates
                ORDER BY updated_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
    return [_row_to_dict(row) for row in rows]


def prune_rejected(*, older_than_days: int = 7) -> int:
    """Delete rejected candidates not updated recently. Returns deleted count."""
    init_db()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=older_than_days)).isoformat()
    with connect() as conn:
        cur = conn.execute(
            """
            DELETE FROM candidates
            WHERE status = 'rejected' AND updated_at < ?
            """,
            (cutoff,),
        )
        return int(cur.rowcount)


def save_listing_draft(asin: str, draft: dict[str, Any]) -> None:
    init_db()
    now = _utc_now()
    asin = asin.strip().upper()
    with connect() as conn:
        conn.execute(
            """
            UPDATE candidates
            SET listing_draft_json = ?, status = CASE
                WHEN status IN ('listed', 'drafted') THEN status
                ELSE 'drafted'
            END, updated_at = ?
            WHERE asin = ?
            """,
            (json.dumps(draft, ensure_ascii=False), now, asin),
        )


def patch_candidate_offer(asin: str, offer_patch: dict[str, Any]) -> bool:
    """Merge keys into existing candidate offer_json. Returns False if ASIN missing."""
    init_db()
    asin = asin.strip().upper()
    with connect() as conn:
        row = conn.execute(
            "SELECT offer_json FROM candidates WHERE asin = ?", (asin,)
        ).fetchone()
        if not row:
            return False
        offer = json.loads(row["offer_json"] or "{}")
        offer.update(offer_patch)
        conn.execute(
            "UPDATE candidates SET offer_json = ?, updated_at = ? WHERE asin = ?",
            (json.dumps(offer, ensure_ascii=False), _utc_now(), asin),
        )
    return True


def get_listing_draft(asin: str) -> dict[str, Any] | None:
    init_db()
    with connect() as conn:
        row = conn.execute(
            "SELECT listing_draft_json FROM candidates WHERE asin = ?",
            (asin.strip().upper(),),
        ).fetchone()
    if not row:
        return None
    raw = row["listing_draft_json"] or ""
    if not raw:
        return None
    return json.loads(raw)


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    keys = set(row.keys())
    draft_raw = row["listing_draft_json"] if "listing_draft_json" in keys else ""
    draft = None
    if draft_raw:
        try:
            draft = json.loads(draft_raw)
        except json.JSONDecodeError:
            draft = None
    return {
        "id": row["id"],
        "asin": row["asin"],
        "title": row["title"],
        "amazon_total": row["amazon_total"],
        "ebay_price": row["ebay_price"],
        "max_amazon_buy": row["max_amazon_buy"],
        "status": row["status"],
        "offer": json.loads(row["offer_json"]),
        "margin": json.loads(row["margin_json"]),
        "hard_reject_reasons": json.loads(row["hard_reject_json"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "listing_draft": draft,
    }
