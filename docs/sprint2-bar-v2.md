# Sprint 2 registered bar v2 (2026-10-19, after vote round 1) - NOT frozen

**Little north star:** the operator drops `upload_items.txt` (Amazon.de links) into `upload_items/`, starts the app with `start.bat`, clicks ONE button, and every link becomes at most one eBay listing on the target the app is set to (Sandbox -> sandbox eBay, Production -> live eBay), without duplicates.

## Two freeze points (changed in v2)
1. **Commitment freeze** (operator's freeze): plan, this bar, card list. Implementation T1-T5 happens AFTER it; that is not a violation.
2. **Measurement freeze**, written by T0/T6 as `sprint2-freeze.json` before run A: tested source SHA (clean worktree), fixture SHA, expected-table SHA, baseline-census SHA, price-snapshot SHA. A pre-run check exits 0 at that SHA and nonzero after a one-byte edit. Any change to those files, or to source between runs A and C, is INCONCLUSIVE (rule 2). The receipt records both freeze points.

## Fixture and registration (S2-T0; all committed before the measurement freeze)
- 20 lines from `bulk/000001.txt`: 12 distinct expected-publishable ASINs (E = 12), 3 alias/repeat lines of E ASINs, 2 junk lines, 2 margin-FAIL ASINs, 1 control ASIN that already has a published sandbox listing. |E| < 10 registered = INCONCLUSIVE.
- A terminal-state/reason enum, and per line `expected_state` + `expected_reason` for runs A, B and C separately.
- **Price snapshot:** the Amazon price/availability used for each row's margin decision. A runtime price that flips a row's margin outcome relative to the snapshot is INCONCLUSIVE for that row (reported, not silently counted); more than 2 flipped rows make the whole measurement INCONCLUSIVE.
- **Baseline census (hashed):** all remote sandbox inventory items and offers, paginated, for every SKU, taken before run A. It includes the smoke listing `DD-SMOKE-TEST-1` (`tools/sandbox_smoke.py`) and the control listing.
- **Control listing:** T0 creates it (or names an existing one) and registers its offerId and itemId. It is tied to the control ASIN.
- **SKU -> ASIN rule:** SKU `DD-<ASIN>` maps to that ASIN. The app also writes the marker `ASIN:<ASIN>` into the inventory item description, so an offer under any other SKU is attributable. Every remote offer is classified E / control / baseline / unknown. A test with an alternate-SKU fixture proves an injected second offer for an E ASIN is detected.

## Measurement (Sandbox only; the first live use is a separate operator decision)
Start with a clean sandbox for E (census shows zero E offers/items). Launch through `start.bat`, click once (**run A**), click again after completion (**run B**, identical re-click), and **run C** below. After each run wait >= 60 s and read the remote sandbox state twice (paginated census, not local files); the two reads must be identical. Receipt `sprint2-run.json`: both freeze points, per-row state, request hosts, timestamps, remote offer/item IDs, the census classification.

**Run C is non-vacuous:** it starts from a reset state with unfinished E rows. The app is killed after at least one remote publish is accepted and before its durable local acknowledgement, with other rows still pending; then restart and resume. The receipt proves that checkpoint (log lines with timestamps and the pending row count at kill).

## Verdict (top to bottom, first match wins)
1. NOT_MET on any: actual request to a production eBay host (a refused or intercepted attempt that sends no outbound request is not one); Amazon cart/purchase action; an ASIN with more than one offer or item across all SKUs (per the SKU->ASIN rule); an offer classified `unknown`; a row whose state or reason differs from its registered expectation for that run (an ordinary E row ending `ERROR_RETRYABLE` only lowers p); a failed control below.
2. INCONCLUSIVE if no violation is seen but: |E| < 10; a frozen file or source SHA changed after the measurement freeze or between runs A and C; the duplicate claim rests only on local files or mocks; two remote reads differ; a required scenario never exercised its action (a publishing scenario with zero publish requests; C5 is judged by rule C5 below, not by this clause); price flips as above.
3. Otherwise p = number of E targets with a published sandbox item: p >= ceil(0.8 |E|) MET; ceil(0.6 |E|) <= p < ceil(0.8 |E|) WEAK; anything else NOT_MET.

## Required controls (outside E and p)
- C1 run B creates 0 new offers/items.
- C2 run C creates 0 duplicates, loses no row (all 20 lines accounted), and the adopted offer/item IDs are unchanged.
- C3 the control ASIN is skipped; its offer/item IDs unchanged.
- C4 a concurrent second click while a run is active is refused (HTTP 409) or attaches to the same run; 0 extra writes.
- C5 Production gate, by interception (no real request): the run request is submitted, the server refuses it (target Production without both flags, or without the server-side `LIVE <n>` confirmation bound to the file hash), and the interception log shows 0 outbound calls; the authorized path is exercised through interception up to the point just before the network; switching the target during a run aborts the run. C5 passes with zero outbound requests.
- C6 an injected ambiguous publish outcome (timeout) keeps the row UNKNOWN until an authoritative remote read; the request log shows no second publish before reconciliation. Fails closed under delayed visibility.

## Live path rules (built in this sprint, used only by operator decision)
Target snapshot per run; Production requires `EBAY_AUTOMATION_ENABLED`, `EBAY_ALLOW_LIST`, and a typed `LIVE <n>` confirmation showing seller, count, file hash; live batch cap `EBAY_LIVE_BATCH_MAX` (default 10, larger files run the first 10 and ask again); stop after 3 consecutive eBay errors; missing/negative margin never publishes.

## Not claimed
Sandbox success is not live behaviour: this sprint proves sandbox behaviour and an intercepted Production gate only. Not claimed: profitability, Amazon data rights, live seller-account behaviour, listing quality at scale, scale beyond 20 rows, variation-group publishing, price stability beyond the snapshot.
