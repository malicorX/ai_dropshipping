# Sprint 2 registered bar v1 (2026-10-19) - NOT yet voted, NOT frozen

**Little north star:** the operator drops `upload_items.txt` (Amazon.de links) into `upload_items/`, starts the app with `start.bat`, clicks ONE button, and every link becomes at most one eBay listing on the target the app is set to (Sandbox -> sandbox eBay, Production -> live eBay), without duplicates.

## Fixture (registered in S2-T0, hash frozen before any run)
20 lines, built from `bulk/000001.txt`: 12 distinct expected-publishable ASINs (E = 12), 3 alias/repeat lines of E ASINs, 2 junk lines, 2 margin-FAIL ASINs, 1 ASIN that already has a published sandbox listing (control, outside E). Each row has a registered `expected_state` and `expected_reason`. |E| < 10 registered = INCONCLUSIVE.

## Measurement (Sandbox only; the first live use is a separate operator decision)
Launch through `start.bat`, click once (run A), click again after completion (run B, identical re-click), and run one kill-mid-run + restart + resume scenario (run C). After each, wait >= 60 s and read the remote sandbox state twice (offers and items per ASIN across ALL SKUs, via the eBay sandbox API, not local files). Receipt `sprint2-run.json`: fixture hash, source SHA, per-row state, request hosts, timestamps, remote offer/item IDs.

## Verdict (top to bottom, first match wins)
1. NOT_MET on any: request to a production eBay host; Amazon cart/purchase action; an ASIN with more than one offer or item across all SKUs; anything created outside E and the registered control; a row whose state or reason differs from its registered expectation (an ordinary E row ending `ERROR_RETRYABLE` only lowers p); a failed control below.
2. INCONCLUSIVE if no violation is seen but: |E| < 10; anything in the fixture, bar or code changed after the freeze or between runs A and C; the duplicate claim rests only on local files or mocks; two remote reads differ; a required scenario sent zero requests.
3. Otherwise p = number of E targets with a published sandbox item: p >= ceil(0.8 |E|) MET; ceil(0.6 |E|) <= p < ceil(0.8 |E|) WEAK; anything else NOT_MET.

## Required controls (outside E and p)
- C1 run B (re-click) creates 0 new offers/items.
- C2 run C (kill mid-run, restart, resume) creates 0 duplicates and loses no row.
- C3 the control ASIN with a published listing is skipped, its offer/item IDs unchanged.
- C4 a concurrent second click while a run is active is refused (HTTP 409) or attaches to the same run; 0 extra writes.
- C5 Production gate, by interception (no real request): Production target without both flags and a server-side confirmation `LIVE <n>` bound to the file hash is refused before any network call; switching the target during a run aborts the run.
- C6 an ambiguous publish outcome (injected timeout) is reconciled by a remote read, never re-sent blindly.

## Live path rules (built in this sprint, used only by operator decision)
Target snapshot per run; Production requires `EBAY_AUTOMATION_ENABLED`, `EBAY_ALLOW_LIST`, and a typed `LIVE <n>` confirmation showing seller, count, file hash; live batch cap `EBAY_LIVE_BATCH_MAX` (default 10, larger files run the first 10 and ask again); stop after 3 consecutive eBay errors; missing/negative margin never publishes.

## Not claimed
Profitability, Amazon data rights, behaviour of a live seller account, listing quality at scale, scale beyond 20 rows, variation-group publishing.
