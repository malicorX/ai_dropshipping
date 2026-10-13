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

Cut line: D items 1-3 mandatory; items 4-5 may move to backlog.
**Not in this sprint:** variation-group publishing, real orders/fulfillment, live eBay, scale beyond 25 rows, profitability claims.

## Plan changes (append-only)
- 2026-10-13: cards re-cut after planning round 1 (consolidation doc); D card added; draft bar replaced by the E-based bar.
