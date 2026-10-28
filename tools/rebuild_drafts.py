"""Rebuild stale listing drafts from fresh Amazon facts (bullets/specs), sequentially.

A draft is stale when it was written before copy was limited to Amazon facts
(it has no ``unsupported_claims_dropped`` key).  Items already listed on eBay
are skipped.  Progress goes to data/rebuild_drafts.jsonl; re-running continues
with whatever is still stale.  Usage: python tools/rebuild_drafts.py [--limit N] [--pause SEC]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dropship_desk import config  # noqa: E402
from dropship_desk.db import get_candidate_by_asin, init_db, list_candidates  # noqa: E402
from dropship_desk.listing_generate import ListingGenerateError, generate_draft  # noqa: E402

SKIP_STATUS = {"listed"}


def stale_asins() -> list[str]:
    out: list[str] = []
    for row in list_candidates(limit=100000):
        if row.get("status") in SKIP_STATUS:
            continue
        full = get_candidate_by_asin(row["asin"]) or {}
        draft = full.get("listing_draft") or {}
        if draft and "unsupported_claims_dropped" not in draft:
            out.append(str(row["asin"]))
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--pause", type=float, default=8.0)
    args = parser.parse_args()
    init_db()
    log = config.DATA_DIR / "rebuild_drafts.jsonl"
    todo = stale_asins()
    if args.limit:
        todo = todo[: args.limit]
    print(f"{len(todo)} stale drafts", flush=True)
    for i, asin in enumerate(todo, 1):
        started = time.time()
        row = get_candidate_by_asin(asin) or {}
        try:
            generate_draft(asin, ebay_price=float(row["ebay_price"]))
            result = {"asin": asin, "ok": True}
        except ListingGenerateError as exc:
            result = {"asin": asin, "ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]}
        except Exception as exc:  # noqa: BLE001 - one bad item must not stop the batch
            result = {"asin": asin, "ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]}
        result["sec"] = round(time.time() - started, 1)
        with log.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(result, ensure_ascii=False) + "\n")
        print(i, len(todo), result, flush=True)
        time.sleep(args.pause)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
