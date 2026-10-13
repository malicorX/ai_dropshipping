Planning declaration: `falsified-by: not-applicable: planning-only sprint roles/tasks from inlined facts; no empirical, code-execution or science acceptance claim`

# Sprint 1 planning brief - ai_dropshipping (Dropship Desk)

You are a planning seat. Tool-loop seats: you MAY read the repo at your cwd read-only, but do not edit, run installers, or run anything interactive. Chat seats: you have no tool loop; everything needed is inlined. Do not invent file names, counts or SHAs. Answer in 400 words or fewer, plain text.

## What the product is
Dropship Desk: a local Windows app (FastAPI + SQLite + React UI) for Amazon.de -> eBay dropshipping. Spec: docs/superpowers/specs/2026-08-09-dropship-desk-design.md. Hard rule: NO live eBay write and NO Amazon purchase; automation flags stay false, Settings stay on eBay Sandbox.

## Measured facts (2026-10-13)
- `pytest -q`: 48 passed. 24 files modified/untracked and UNCOMMITTED on main (variation_expand.py, amazon/variations.py, bulk/, tests/conftest.py, README_100k.md ...). HEAD 1f63e8d.
- `bulk/000001.txt` = 312 Amazon.de product URLs (one per line, with /dp/<ASIN>/ref=... tails; many are variants of one product family, e.g. Mission dart cases by country).
- Existing pipeline pieces: enrich.py, margin.py, evaluate_service.py, find_job.py, listing_template.py, ollama_client.py (unique copy), product_media.py, ebay/listing.py (unpublished offer then publish), variation_expand.py (parent/child ASIN expansion), api.py endpoints (/api/evaluate, /api/listing/generate, /api/ebay/listings/{asin}/stage and /publish).
- Duplicate handling found by `grep -n -i "dup\|unique" dropship_desk`: only a UNIQUE index on candidates.asin (db.py:64-66, _dedupe_asins) and child-ASIN de-dup inside variation_expand.py. Nothing found that checks whether an eBay listing/offer for the same ASIN/SKU already exists, nor that dedupes URLs that normalise to the same ASIN, nor near-duplicate titles. Treat this as "not found by grep", not proven absent.

## The operator's requirement (verbatim intent)
"Take a list of Amazon item-links and have the dropshipper analyse and parse those, and create an eBay listing for each entry. We have to check not to upload duplicates and so on."

## Goal chosen by the operator for Sprint 1 (about one week), draft bar
Take ASINs from bulk/000001.txt through parse -> enrich -> margin PASS/FAIL -> draft -> variation expand -> unpublished offer -> publish, in eBay SANDBOX only. Draft bar: a registered seeded sample of 25 URLs (to include seeded duplicate URLs, URL variants that normalise to the same ASIN, and a re-run), MET if >=20 of 25 reach a published sandbox item, zero duplicate sandbox listings after a second identical run, 0 live writes, 0 Amazon purchases.

## Your job
1. ROLE: choose the one role you would hold (planner, builder, tester, reviewer, critic) and why. Rule: the builder never reviews own work; the critic is from a different model family than the builder.
2. TASKS: propose the card list for the week (each: definition of done, size S/M, dependency, role). Existing draft cards: T0 registration, T1 land the dirty tree, T2 batch runner, T3 drafts+variations, T4 sandbox send/publish + live-write guard, T5 one measurement run, T6 independent review. Add, drop or re-cut; in particular a DEDUP card: say exactly what "duplicate" means (same ASIN via different URL forms? same ASIN already in DB? already on eBay by SKU/offer? near-identical title/variation siblings? same product from two parents?) and the checkable test for each.
3. BAR: fix what is wrong with the draft bar. Give the exact registered rule, how a margin-FAIL or a deliberately-rejected duplicate counts, and what the sample must contain.
4. FAILURE: what would make the sprint a failure even if every card is Done.
5. STRONGEST OBJECTION to your own plan.
6. Name the answer you should not give: a diplomatic middle that changes nothing.
End with one line: **the single task you would do first, and the result that would falsify your plan.**
