## Bar v2.4 - decision table and dedup obligations (vote rounds 1-3, 2026-10-13)

**Identity.** One identity = (configured eBay marketplace, ASIN, SKU `DD-<ASIN>`). Counts key on this tuple and also per ASIN across ALL SKUs in the marketplace, so an alternate SKU cannot hide a duplicate.

**Registered rows.** T0 registers for every row `expected_state` and `expected_reason`. Two rows are *controls*, run in a separate control run and not in E or p: (C1) the M2 alternate-SKU fixture, expected `DUPLICATE_DETECTED` / `duplicate_asin_across_skus`; (C2) the guard row: a stubbed production host / credential mismatch, expected refusal before any request. A control that does what it should has no effect on the verdict; a control that fails to detect or refuse -> NOT_MET. Controls are excluded from the duplicate counts of rule 2b.

**Verdict, evaluated top to bottom, first match wins**
1. Any request to a production eBay host (other than a stubbed C2 attempt that was refused), any live write, or any Amazon purchase -> **NOT_MET**.
2. **NOT_MET** if ANY (this rule outranks every INCONCLUSIVE cause below, e.g. |E|=12 plus a duplicate read is NOT_MET) read after either scored run shows:
   2a. a row whose terminal state or reason differs from its registered `expected_state` / `expected_reason` - except an expected-'published' row that ends `ERROR_RETRYABLE` or unpublished, which only lowers p. The exception applies to ordinary E rows only. 2a applies to ALL rows, including the mandatory scenarios M1-M5 and the 'also required' cases, which must in addition satisfy 2d (2d supplements 2a, never replaces it): an M3 target that ends `ERROR_RETRYABLE` is NOT_MET even if remote shows 1 / 1. A published row with the wrong reason IS a mismatch;
   2b. an identity, or an ASIN across all SKUs, with more than one offer or published item;
   2c. a first or second run creating anything not registered in E or the baseline;
   2d. an executed mandatory scenario (M1-M5 or the 'also required' cases) (at least one request of the scenario's action was sent; 'could not be executed' in rule 3 means zero were sent) whose remote result differs from its table row: counts, offerId/listingId, or a send while remote state was unresolved;
   2e. a failed control (C1 undetected, C2 not refused).
3. **INCONCLUSIVE** (only when rule 2 found no violation) if: registered |E| < 15 (T0 must register >= 15; 10-14 counts as under-registered); any change after the freeze to the sample, expected outcomes, E or the frozen docs, or any code change between the first and second scored run; or a dedup claim backed only by local files/mocks.
   Also INCONCLUSIVE (rule 2 found no violation) if two remote reads after the settle wait differ, or a mandatory scenario could not be executed in the window. A scenario is never dropped and never MET by omission.
4. p = published targets in E: p >= ceil(0.8|E|) -> **MET**; ceil(0.6|E|) <= p < ceil(0.8|E|) -> **WEAK**; else **NOT_MET**.
Worked example: |E| = 15, 3 targets end ERROR_RETRYABLE, all other rows correct, no duplicates, controls pass -> p = 12 = ceil(0.8*15) -> MET. Same, but one published row has the wrong reason -> NOT_MET (2a). M3 target ends ERROR_RETRYABLE, remote 1 / 1 -> NOT_MET (2a); remote 1 / 0 -> NOT_MET (2a and 2d). M1 with every request 5xx, remote 0 / 0 -> NOT_MET (2d), not INCONCLUSIVE, because requests were sent.
Remote reads happen after a registered settle wait (>= 60 s) and are repeated twice.

**Mandatory dedup scenarios (card #16, all mandatory, no cut)**
| id | start state | action | required remote result (offers / published items per identity) |
|---|---|---|---|
| M1 | URL aliases and an exact repeat of one ASIN | run | 1 / 1 |
| M2 | sandbox offer + item for `DD-<ASIN>` exist, local state deleted | run | unchanged, 1 / 1; same offerId and listingId (control C1 covers the alternate-SKU variant) |
| M3 | unpublished offer exists | run | resumed and published, 1 / 1 |
| M4 | publish returns an ambiguous result or times out | retry | 1 / 1; unresolved remote state blocks sending |
| M5 | two concurrent runs, same ASIN | both | 1 / 1 |
Also required: a DB-only candidate stays eligible and publishes; a child reachable from two parents appears once. Near-title flag: flag only, rule registered in T0, outside the bar.

**Receipt.** Timestamped remote observations for every read: marketplace, ASIN, all observed SKUs, offer/item IDs, per-identity and per-ASIN counts, `hosts_contacted`; per-row JSON `asin`, `sku`, `terminal_state`, `reason`, `offer_id`, `item_id`. Retryable network / 429 / 5xx errors map to `ERROR_RETRYABLE` after bounded retries and never count as published.

**Freeze and T1.** T1 (land the dirty tree) lands BEFORE the freeze comment; the freeze comment records the T1 SHA and the SHA of the frozen docs; the receipt records both. T0 asserts `git diff --name-only <freeze-SHA>..<run-HEAD>` lists no frozen doc or sample file.
