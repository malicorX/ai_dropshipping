Planning declaration: `falsified-by: not-applicable: planning-only commitment vote on a sprint package from inlined facts; no empirical, code-execution or science acceptance claim`

Everything inlined; run nothing, invent nothing. 150 words or fewer.

Sprint 1 ai_dropshipping, vote ROUND 3 (DELTA only). Round 2: deepcode and nv-nemotron APPROVE-AS-IS; codex, deepseek, gpt6-luna-max, gpt61-sol, opus REQUEST-CHANGES. Applied in commit 70849ed (texts below): per-ASIN-across-all-SKUs duplicate -> NOT_MET with an alternate-SKU fixture in M2 (codex, luna, sol); rule 4/5 collision resolved with a worked example (opus); differing remote reads and an unexecutable mandatory scenario -> INCONCLUSIVE (opus, deepcode); expected_reason compared (luna); receipt keeps timestamped remote observations (sol); T0 asserts frozen docs untouched between frozen SHA and T1 SHA (deepcode). REJECTED: deepseek's move of M4/M5 to Sprint 2 - codex, sol, luna and opus want them kept and cutting reopens round 1's cut-line objection.
ORDERING: codex, deepseek, luna want T1 (land the dirty tree) BEFORE the freeze so the freeze pins a real SHA; deepcode, nv-nemotron, sol, opus accept T1 after the freeze if its SHA is recorded. The operator has not ruled. Treat this as: T1 lands before the freeze comment, and the freeze comment records the T1 SHA, unless the operator says otherwise. If you cannot accept that, say why.
STRONGEST CASE AGAINST: the verdict table is now long; a long table can hide a hole.

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

QUESTIONS
1. `VOTE: APPROVE-AS-IS | REQUEST-CHANGES | REJECT`
2. At most 2 exact, checkable changes with done conditions.
3. Name any case the table still leaves without exactly one verdict.
