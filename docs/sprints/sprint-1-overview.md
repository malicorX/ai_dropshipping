# Sprint 1 overview (archived 2026-10-19): SUPERSEDED, NEVER FROZEN, NEVER RUN

Goal: bulk list of Amazon links -> sandbox eBay listings, one per ASIN (25-row bar v2.5, commitment vote r7 unanimous 7/7).
Outcome: no card started. On 2026-10-19 the operator asked for a narrower, UI-driven goal that includes a live path; it is Sprint 2. Sprint 1's invariants (one listing per ASIN, duplicate detection across SKUs, remote-read verification, two reads >= 60 s apart) are carried into Sprint 2. Nothing from Sprint 1 was measured, so no verdict exists. Verdict: SUPERSEDED (not MET, not NOT_MET).
Direction check (Rule 8, self-assessment): the Sprint 1 package consumed seven vote rounds on a 25-row bar and produced no product benefit; the operator's own sandbox smoke test (tools/sandbox_smoke.py) produced the first proven end-to-end publish within hours. Decision: KURS ANDERN - smaller bar, user-visible deliverable first, heavy registration kept only for the duplicate and live-guard claims.
Last at-a-glance text before retargeting:

Rolling page. Sprint 1: PLANNED, not frozen. Commitment vote r7 unanimous (7/7). Waiting for: T1 (land the dirty tree, needs operator go) and the operator's freeze. Cards: 0 started, 10 planned. Plan #13, goal #3, docs/sprint1-commitment-consolidation-2026-10-13.md.
