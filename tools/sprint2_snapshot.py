"""Sprint 2 T0 helper: snapshot Amazon.de price/availability for candidate ASINs and record the
margin gate outcome. Uses the installed Chrome (channel=chrome): the bundled Chromium is reset by amazon.de.

  python tools/sprint2_snapshot.py --n 45 --out sprint2/price-snapshot.json
Read-only toward Amazon (page loads only, no cart, no purchase). No eBay request.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dropship_desk.amazon import product as P  # noqa: E402
from dropship_desk.asin import extract_asin, hard_reject_reasons  # noqa: E402
from dropship_desk.db import get_margin_settings  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def load_asins(n: int) -> list[str]:
    seen: list[str] = []
    for line in (ROOT / "bulk" / "000001.txt").read_text(encoding="utf-8").splitlines():
        a = extract_asin(line.strip())
        if a and a not in seen:
            seen.append(a.upper())
    return seen[:n]


def snap(page, asin: str) -> dict:
    url = f"https://www.amazon.de/dp/{asin}"
    page.goto(url, wait_until="domcontentloaded", timeout=45_000)
    time.sleep(1.5)
    html = page.content()
    if P._looks_like_captcha(html):
        return {"asin": asin, "error": "captcha"}
    raw = page.evaluate(P._PDP_EXTRACT_JS) or {}
    offer = P._offer_from_raw(asin, url, raw)
    rejects = hard_reject_reasons(offer, get_margin_settings())
    return {
        "asin": asin,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "host": "www.amazon.de",
        "field": "pdp.price",
        "amazon_total": offer.amazon_total,
        "stars": offer.stars,
        "reviews": offer.reviews,
        "in_stock": offer.in_stock,
        "has_variations": bool(raw.get("has_variations")),
        "title": offer.title[:90],
        "hard_rejects": list(rejects),
        "margin_gate": "PASS" if not rejects else "FAIL",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=45)
    ap.add_argument("--out", default="sprint2/price-snapshot.json")
    ap.add_argument("--pause", type=float, default=4.0)
    a = ap.parse_args()
    from playwright.sync_api import sync_playwright

    rows: list[dict] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        ctx = browser.new_context(locale="de-DE")
        page = ctx.new_page()
        for asin in load_asins(a.n):
            try:
                row = snap(page, asin)
            except Exception as e:  # noqa: BLE001
                row = {"asin": asin, "error": str(e)[:160]}
            rows.append(row)
            print(asin, row.get("margin_gate") or row.get("error"), flush=True)
            time.sleep(a.pause)
        browser.close()
    (ROOT / a.out).write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    ok = sum(1 for r in rows if r.get("margin_gate"))
    print(f"done: {ok}/{len(rows)} fetched")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
