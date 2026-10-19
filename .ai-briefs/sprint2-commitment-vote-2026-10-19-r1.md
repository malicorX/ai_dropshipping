# Sprint 2 commitment vote r1 (2026-10-19) - ai_dropshipping

You are a voting seat. Answer in <=250 words. You may read the repo (cwd). The package below is PLANNED, not frozen; nothing has been executed (no card started; only planning docs and board issues exist).

Honest disclosure of what is already executed: Sprint 1 was superseded (never run). tools/sandbox_smoke.py (not a sprint card) published one synthetic sandbox listing with the new test user on 2026-10-19.

Questions:
1. `VOTE: APPROVE-AS-IS | REQUEST-CHANGES | REJECT`
2. At most 3 exact, checkable changes, each with a done condition, and which change would move your vote to APPROVE-AS-IS.
3. The one risk left even if approved.
4. Is anything already executed a problem for freezing? (one sentence)

---- PLAN ----
Repos in this sprint: ai_dropshipping

# Sprint 2 plan (PLANNED, NOT FROZEN) - 2026-10-19

**Goal:** `upload_items/upload_items.txt` + `start.bat` + one UI button -> every Amazon link becomes at most one eBay listing on the app's current target (Sandbox -> sandbox, Production -> live). **Bar:** `docs/sprint2-bar-v1.md`. **Consolidation:** `docs/sprint2-planning-consolidation-2026-10-19.md`.

## Roles
Planner/driver/integrator: this session (never builds). Builder: codex. Tester: deepcode. Reviewer: opus. Critic: deepseek.

## Cards
| card | what | size | dep |
|---|---|---|---|
| T0 | register: fixture (20 lines, E=12), expected states, hash, bar, receipt contract | S | - |
| T1 | reader + durable run/row ledger, alias dedupe, resumable | S | T0 |
| T2 | pipeline worker: analyse -> margin -> draft -> stage -> publish, sequential background job, continue on error, single-flight lock | M | T1 |
| T3 | duplicate reconciliation: remote check across SKUs, adopt/resume existing offers, unknown outcome blocks resend | M | T2 |
| T4 | target pin + live gate: snapshot env, abort on switch, server-side `LIVE <n>` bound to file hash, cap, interception tests | M | T2 |
| T5 | UI + start.bat: one button, progress table, reattach after reload, env banner, actionable errors | M | T2 |
| T6 | measurement: runs A/B/C + controls, one receipt | M | T3-T5 |
| T7 | independent review (opus) and critic (deepseek) of receipt, dedupe, gate | S | T6 |
| REVIEW | sprint review | S | T7 |

**Not in this sprint:** first real live listing, variation groups, near-duplicate product detection, scale beyond 20 rows, profitability.

## Plan changes (append-only)
(none yet)

---- BAR ----
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
