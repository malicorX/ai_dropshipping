# Sprint process (ai_dropshipping)

Modelled on malicorX/projects/18 (ai_rsiHelper). Authority for the generic ceremony: the `go-on-sprint-*` skills.

## Board coordinates

| what | value |
|---|---|
| owner | malicorX |
| project number | 24 (https://github.com/users/malicorX/projects/24) |
| repo | malicorX/ai_dropshipping |
| repos in a sprint | ai_dropshipping (single-repo program) |

## Structure (fixed)

- Pinned, never per-sprint: #1 NORTH STAR + sprint ledger, #14 at-a-glance (rolling), #15 rules.
- Per sprint: container -> goal, plan, `Tasks - ai_dropshipping` (-> cards), REVIEW.
- Status: Backlog / Ready / In progress / In review / Done / Blocked. Role fields: Builder, Review by, Tester, Critic, Integrator, Problems & ideas.
- Session ids: `sprint<N>-dropshipping-<card>`.

## Hard safety rule for every sprint (revised 2026-10-19 by the operator)

No Amazon purchase, ever. No live eBay write during a sprint measurement or a test: the measured bar must be reachable in Sandbox only. A live path may be BUILT behind the gate (both flags `EBAY_AUTOMATION_ENABLED` + `EBAY_ALLOW_LIST`, server-side typed confirmation, batch cap); its first real use is a separate operator decision. Default settings: flags false, Settings on Sandbox. (Sprint 1 said "no live write, ever"; superseded by the operator's Sprint 2 goal.)

## Sprint 1 (2026-10-13): SUPERSEDED, never frozen, never run (archive: docs/sprints/sprint-1-overview.md)

Container #2, goal #3, plan #13, tasks #4 (cards #5-#11), REVIEW #12. Goal: bulk URLs -> sandbox-published items, bar 20/25, 0 live writes.
Pending: planning round, rating round, commitment vote, operator freeze.

## Sprint 2 (2026-10-19): FROZEN (vote r7 unanimous 6/6, operator froze)
Goal: `upload_items/upload_items.txt` + start.bat + one UI button -> one eBay listing per Amazon link on the app's current target. Plan `docs/sprint2-plan.md`, bar `docs/sprint2-bar-v7.md`. Session ids `sprint2-dropshipping-<card>`.
