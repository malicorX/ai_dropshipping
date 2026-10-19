# Sprint 2 planning brief (goal already chosen by the operator) - ai_dropshipping

You are a planning seat. You may read the repo at your cwd (commit 9958854 on main). Answer in <=450 words, no preamble.

## Goal (operator, verbatim intent, 2026-10-19)
The operator puts a text file `upload_items.txt` (one or more Amazon.de links) into `M:\Data\Projects\ai_dropshipping\upload_items`, starts the app with `start.bat`, and clicks ONE button in the UI. The button reads that file and processes every link: parse -> analyse (enrich, margin) -> listing draft -> eBay offer. If the app is in Sandbox mode the listings land in sandbox eBay; otherwise (Production mode) on live eBay. No duplicates (the same ASIN must not become two listings).

## Facts you can rely on
- App: FastAPI + SQLite + React ("Dropship Desk"). Existing per-ASIN steps: analyse/enrich, draft, `ebay/listing.py` stage_unpublished + publish_offer (SKU `DD-<ASIN>`), UI Settings switch Sandbox/Production (`/api/ebay/target`). Live write is gated by `check_ebay_sell` (production needs EBAY_AUTOMATION_ENABLED + EBAY_ALLOW_LIST + `confirm_live`).
- `tools/sandbox_smoke.py` proves a sandbox publish works end to end with the NEW sandbox test user (listing 110591224930, 2026-10-19). pytest: 50 passed.
- `upload_items/` already exists in the repo folder (operator-created, contains a `___DONT_USE_THIS.txt` and an `evaluated/` folder; contents are the operator's, not specified).
- Superseded plan: Sprint 1 (bulk list -> sandbox, 25-row bar v2.5, voted 7/7, never frozen, never run). Its useful parts: one listing per ASIN, duplicate detection across SKUs, remote-read verification. Its rule "no live write ever" is CHANGED by this goal: the operator explicitly wants Production mode to publish live.

## Not allowed
No Amazon purchase/cart action. No live eBay write while planning or testing in this sprint's measurement: the measured bar must be reachable with Sandbox only. A live path may be BUILT, but its first real use is a separate operator decision outside the sprint bar.

## Questions
1. ROLE you would take (planner/builder/tester/reviewer/critic).
2. Tasks: each with one-line definition of done, size S/M, dependencies, role. Max 8.
3. The REGISTERED BAR: what run artifact/count decides MET / WEAK / NOT_MET (never "tasks done"). One bar, numbers.
4. SAFEGUARDS for the live path (what stops a mistaken live listing; what is the confirm step; what happens on partial failure, re-click, a file with 50 links).
5. What makes the sprint a failure even if every task is done.
6. Strongest objection to this goal or to your own plan.
