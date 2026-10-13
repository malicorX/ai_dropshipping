Planning declaration: `falsified-by: not-applicable: planning-only commitment vote on a sprint package from inlined facts; no empirical, code-execution or science acceptance claim`

Everything is inlined; run nothing, invent no file names or counts. 200 words or fewer.

Sprint 1 of ai_dropshipping, vote ROUND 2 (round 1 on 2026-10-13: codex, deepcode, deepseek, gpt6-luna-max, gpt61-sol, nv-nemotron all REQUEST-CHANGES; opus had no quota). Only the DELTA is below, plus the strongest case against it. Executed so far: planning and board setup only; the dirty tree is still uncommitted, T1 lands it before any implementation seat starts and its SHA is recorded in the plan.

DELTA (applied in docs/sprint1-plan.md, commit d3b3e06): the bar v2 text below. It answers your round-1 requests: undefined cut line -> five mandatory scenarios M1-M5, no cut; |E| 10-14 hole and WEAK precedence -> decision table; identity undefined -> (marketplace, ASIN, SKU) tuple plus per-ASIN count across SKUs; freeze pins a recorded SHA; guard shown failing first; T0 script contract. REJECTED: nv-nemotron's cosine threshold (near-title is a flag outside the bar) and failure-mode matrix (one rule: bounded retry -> ERROR_RETRYABLE). NOT DONE: deepseek's "commit the dirty tree before the freeze" - kept as T1 before implementation, with its SHA recorded; the operator has not ruled on the ordering.

STRONGEST CASE AGAINST THE DELTA: registered |E| >= 15 plus five mandatory remote scenarios in an M-size card may not fit one week.

## Bar v2 - decision table and dedup obligations (vote round 1 changes, 2026-10-13)

**Identity.** One identity = (configured eBay marketplace, ASIN, SKU `DD-<ASIN>`). All counts key on this tuple. Listings are also counted per ASIN across all SKUs, so an alternative SKU cannot hide a duplicate.

**Verdict, evaluated top to bottom, first match wins**
1. Any request to a production eBay host, any live write, or any Amazon purchase -> **NOT_MET** (nothing below can override).
2. Any unregistered change to sample, expected outcomes, E, code under test or the frozen docs between registration and the run, or a dedup claim backed only by local files/mocks -> **INCONCLUSIVE**.
3. Registered |E| < 15 (T0 must register >= 15; 10-14 counts as under-registered) -> **INCONCLUSIVE**.
4. Any row with a wrong terminal state or reason, or any identity with more than one offer or item after either run, or a second run that creates anything -> **NOT_MET**.
5. p = published targets in E: p >= ceil(0.8|E|) -> **MET**; ceil(0.6|E|) <= p < ceil(0.8|E|) -> **WEAK**; else **NOT_MET**.
Remote reads happen after a registered settle wait (>= 60 s) and are repeated twice with identical results, to avoid reading before the sandbox propagates.

**Mandatory dedup scenarios (card #16, all five are inside the sprint, none can be cut)**
| id | start state | action | required remote result (offers / published items per identity) |
|---|---|---|---|
| M1 | URL aliases and an exact repeat of one ASIN | run | 1 / 1 |
| M2 | sandbox offer + item for `DD-<ASIN>` exist, local state deleted | run | unchanged, 1 / 1; same offerId and listingId |
| M3 | unpublished offer exists | run | resumed and published, 1 / 1 |
| M4 | publish returns ambiguous result or times out | retry | 1 / 1; unresolved remote state blocks sending |
| M5 | two concurrent runs, same ASIN | both | 1 / 1 |
Also required (not cuttable): DB-only candidate stays eligible and publishes; a child reachable from two parents appears once. Near-title flag stays optional (flag only; rule registered in T0; outside the bar).

**Guard.** The live-write guard is shown failing first: a stubbed production host / credential mismatch produces a refusal row before any request is sent.

**T0 contract additions.** The measure script reads rows (row id, URL, expected state) and writes JSON per row: `asin`, `sku`, `terminal_state`, `reason`, `offer_id`, `item_id`, `hosts_contacted`. Retryable network / 429 / 5xx errors map to a registered `ERROR_RETRYABLE` terminal state after a bounded number of retries; they never count as published.

**Freeze pins.** The freeze comment records the commit SHA of the frozen docs; the receipt records the same SHA. T1 (land the dirty tree) must be done and its SHA recorded in the plan before any implementation seat starts.

QUESTIONS
1. `VOTE: APPROVE-AS-IS | REQUEST-CHANGES | REJECT`
2. At most 2 exact, checkable changes, each with a done condition.
3. Is the T1-after-freeze ordering a blocker for you? One sentence.
