# Sprint 2 planning consolidation (2026-10-19)

Brief: `.ai-briefs/sprint2-plan-round2-2026-10-19.md` (goal given by the operator, so no candidate-goal round). Session `sprint2-dropshipping-plan`.
Roster used: codex, gpt61-sol, gpt6-luna-max, opus, deepcode, deepseek. **nv-nemotron** returned only tool-call text, no plan: recorded as no answer. Skipped: kimi, grok (quota), mimo-* ($0), Fable (banned).

| seat | role taken | fixture | key points |
|---|---|---|---|
| codex | planner | 50 lines, E=30 | durable run/row checkpoints, unique claims, confirm_live bound to seller+file hash+count, single-use 5-min authorization |
| gpt61-sol | planner | 50 lines, E=25 | alternate-SKU adoption, stop treating HTTP 400 as absence, 2 remote censuses, test Production by interception only |
| gpt6-luna-max | planner | 50 rows, E>=15 | per-ASIN lock, reject files >50 lines, one stale price can mass-publish |
| opus | critic/reviewer | 10 lines | remote GET before staging, LIVE <n> typing, live cap 10, stop at first 5xx, config-set path, 409 on re-click |
| deepcode | planner | 12 lines | ledger, extract steps into callables (no HTTP self-calls), UNKNOWN state, single-flight lock |
| deepseek | planner+critic | 5 lines | UI banner env, batch cap 10, idempotency key (asin, env), blocked Amazon enrichment may push junk live |

## Decided
- **Goal as given by the operator.** Path `upload_items/upload_items.txt` under the app root; ignore `___DONT_USE_THIS.txt` and `evaluated/`; path configurable.
- **Fixture size 20 lines, E = 12** (between deepseek's 5 and codex's 50: one week, still covers aliases, junk, margin-FAIL, a control and three recovery scenarios). Bar reuses the Sprint 1 verdict precedence (violations first, then INCONCLUSIVE, then p).
- **Live safeguards converge across 5 families and are adopted:** server-side target snapshot per run, typed `LIVE <n>` bound to the file hash, both existing flags, cap 10 (`EBAY_LIVE_BATCH_MAX`), stop after consecutive errors, ambiguous publish reconciled by remote read, single-flight lock. Production is tested by interception only; first real live use is a separate operator decision outside the bar.
- **Rule change, recorded:** Sprint 1's "no live write, ever" is replaced by "no live write during measurement; a live path may be built behind the gate". Operator instruction 2026-10-19: Production mode publishes live.
- Roles: builder codex; tester deepcode; reviewer opus; critic deepseek; planner/driver/integrator this session. Fallbacks gpt61-sol, gpt6-luna-max (same family as codex, never review it).

## Rejected / deferred
- 50-line fixture and 28-publication bar (codex, sol, luna): too large for the week; the larger file goes to backlog as the scale test.
- Single-use 5-minute authorization token (codex): the typed `LIVE <n>` bound to the file hash gives the same protection; token expiry deferred.
- Near-duplicate product detection across ASINs (nemotron's objection, also in Sprint 1): review flag only, backlog.
- Variation-group publishing: backlog #17.
- Sprint 1: SUPERSEDED, archived in `docs/sprints/sprint-1-overview.md`.
