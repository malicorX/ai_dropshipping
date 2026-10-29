"""Read-only: how many drafted items get a verified eBay category + aspects automatically?"""
from __future__ import annotations
import collections, json, sqlite3, sys
from dropship_desk import config
from dropship_desk.ebay import aspects as A, client, taxonomy

def main() -> None:
    db = sqlite3.connect("data/dropship.sqlite3"); db.row_factory = sqlite3.Row
    rows = db.execute("select asin,title,offer_json from candidates where status in ('drafted','ready')").fetchall()
    out, tally = [], collections.Counter()
    with config.ebay_operation("production"):
        for r in rows:
            offer = json.loads(r["offer_json"] or "{}")
            try:
                v = taxonomy.verified_listing_specifics(r["asin"], offer.get("title") or r["title"], r["title"], offer)
                res, why = "ok", v["category_name"]
            except A.AspectsUnverified as e:
                res, why = str(e).split(":")[0], str(e)[:220]
            except Exception as e:  # noqa: BLE001
                res, why = "error", str(e)[:200]
            tally[res] += 1
            out.append({"asin": r["asin"], "result": res, "detail": why})
    json.dump(out, open("data/category_coverage.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(dict(tally), len(rows))

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8"); main()
