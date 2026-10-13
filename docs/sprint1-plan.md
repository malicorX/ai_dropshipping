Repos in this sprint: ai_dropshipping

# Sprint 1 plan (PLANNED, NOT FROZEN) - 2026-10-13

**Goal (#3):** given a list of Amazon.de item links, the app parses/analyses each and creates one sandbox eBay listing per distinct ASIN, no duplicates, no live side effects.
**Operator decisions:** goal picked 2026-10-13; one listing per ASIN (variation groups -> backlog #17).
**Bar:** see issue #3 and docs/sprint1-planning-consolidation-2026-10-13.md. 25 rows seeded from bulk/000001.txt; E = expected unique margin-PASS targets (>=15, <10 = INCONCLUSIVE); MET iff all rows correct terminal state, >= ceil(0.8|E|) published, after identical rerun exactly one offer/item per identity read from the eBay sandbox API, 0 production hosts, 0 purchases, 0 live writes.

## Roles
Planner/driver/integrator: this session (Sonnet 5.5, never builds). Builder: codex. Tester: deepcode. Reviewer: opus. Critic: deepseek. Fallbacks: gpt61-sol, gpt6-luna-max (same family as codex: never review codex).

## Cards (parent #4)
| card | what | size | dep |
|---|---|---|---|
| #5 T0 | registration: sample, per-row expected outcomes, E, bar, measure script contract | S | - |
| #6 T1 | land the dirty tree (seats only see committed HEAD) | M | T0 |
| #7 T2 | URL normalisation + resumable batch runner, terminal state per row | M | T1 |
| #16 D | dedup: remote SKU reconciliation, DB-only eligibility, retry/concurrency | M | T2 |
| #8 T3 | child expansion, margin gate, drafts per ASIN, near-title flag | M | T2 |
| #9 T4 | sandbox stage/publish + network-level live-write guard with refusal test | M | T3, D |
| #10 T5 | one run + identical rerun, one receipt | S | T4 |
| #11 T6 | independent review + critic | S | T5 |
| #12 REVIEW | sprint review | S | T6 |

No cut line inside D: scenarios M1-M5 below are all mandatory.
**Not in this sprint:** variation-group publishing, real orders/fulfillment, live eBay, scale beyond 25 rows, profitability claims.

## Plan changes (append-only)
- 2026-10-13 (vote r2): per-ASIN-across-SKUs NOT_MET, rule 4/5 worked example, differing reads / unexecutable scenario -> INCONCLUSIVE, expected_reason, receipt observations, frozen-file assertion. Rejected: deepseek's move of M4/M5 to Sprint 2 (codex, sol, luna, opus keep them; cutting reopens round 1's cut-line objection).
- 2026-10-13 (vote r1): bar v2 added (verdict table, identity tuple, M1-M5, guard-fails-first, freeze pins SHA). Rejected: nv-nemotron cosine threshold (near-title is flag-only, outside the bar) and a full failure-mode matrix (one rule: bounded retry -> ERROR_RETRYABLE).
- 2026-10-13: cards re-cut after planning round 1 (consolidation doc); D card added; draft bar replaced by the E-based bar.
## Bar v2 - decision table and dedup obligations (vote round 1 changes, 2026-10-13)

**Identity.** One identity = (configured eBay marketplace, ASIN, SKU `DD-<ASIN>`). All counts key on this tuple. Listings are also counted per ASIN across all SKUs, so an alternative SKU cannot hide a duplicate.

**Verdict, evaluated top to bottom, first match wins**
1. Any request to a production eBay host, any live write, or any Amazon purchase -> **NOT_MET** (nothing below can override).
2. Two remote reads after the settle wait that differ, or a mandatory scenario that could not be executed in the window -> **INCONCLUSIVE** (a scenario is never dropped and never MET by omission).
2b. Any unregistered change to sample, expected outcomes, E, code under test or the frozen docs between registration and the run, or a dedup claim backed only by local files/mocks -> **INCONCLUSIVE**.
3. Registered |E| < 15 (T0 must register >= 15; 10-14 counts as under-registered) -> **INCONCLUSIVE**.
4. Any row whose terminal state or reason differs from its registered `expected_state` / `expected_reason` **and whose expected state is not 'published'**; or any identity, or any ASIN counted across ALL SKUs in the marketplace, with more than one offer or published item after either run (an alternate-SKU duplicate is NOT_MET even if each SKU has one); or a second run that creates anything -> **NOT_MET**.
An expected-'published' target that ends `ERROR_RETRYABLE` or unpublished is not a rule-4 error; it only lowers p in rule 5. Worked example: |E| = 15, 3 targets end ERROR_RETRYABLE, no duplicates, all other rows correct -> p = 12 = ceil(0.8*15) -> MET.
5. p = published targets in E: p >= ceil(0.8|E|) -> **MET**; ceil(0.6|E|) <= p < ceil(0.8|E|) -> **WEAK**; else **NOT_MET**.
Remote reads happen after a registered settle wait (>= 60 s) and are repeated twice with identical results, to avoid reading before the sandbox propagates.

**Mandatory dedup scenarios (card #16, all five are inside the sprint, none can be cut)**
| id | start state | action | required remote result (offers / published items per identity) |
|---|---|---|---|
| M1 | URL aliases and an exact repeat of one ASIN | run | 1 / 1 |
| M2 | sandbox offer + item for `DD-<ASIN>` exist, local state deleted; a second fixture has the same ASIN under an alternate SKU | run | unchanged, 1 / 1; same offerId and listingId; the alternate-SKU case is detected by the per-ASIN aggregate and fails the run |
| M3 | unpublished offer exists | run | resumed and published, 1 / 1 |
| M4 | publish returns ambiguous result or times out | retry | 1 / 1; unresolved remote state blocks sending |
| M5 | two concurrent runs, same ASIN | both | 1 / 1 |
Also required (not cuttable): DB-only candidate stays eligible and publishes; a child reachable from two parents appears once. Near-title flag stays optional (flag only; rule registered in T0; outside the bar).

**Guard.** The live-write guard is shown failing first: a stubbed production host / credential mismatch produces a refusal row before any request is sent.

**T0 contract additions.** The measure script reads rows (row id, URL, expected state) and writes JSON per row: `asin`, `sku`, `terminal_state`, `reason`, `offer_id`, `item_id`, `hosts_contacted`. Retryable network / 429 / 5xx errors map to a registered `ERROR_RETRYABLE` terminal state after a bounded number of retries; they never count as published.

**Freeze pins.** The freeze comment records the commit SHA of the frozen docs; the receipt records the same SHA. T1 (land the dirty tree) must be done and its SHA recorded in the plan before any implementation seat starts.

**Receipt.** Retains timestamped remote observations for every post-run read: marketplace, ASIN, all observed SKUs, offer/item IDs, per-identity and per-ASIN counts. T0 registers `expected_state` and `expected_reason` per row and the receipt compares both. T0 also prints `git diff --name-only <frozen-SHA>..<T1-SHA>` and asserts the frozen docs are untouched; the T1 SHA is rule 2b's baseline for 'code under test'.
