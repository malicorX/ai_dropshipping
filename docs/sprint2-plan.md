Repos in this sprint: ai_dropshipping

# Sprint 2 plan (PLANNED, NOT FROZEN) - 2026-10-19

**Goal:** `upload_items/upload_items.txt` + `start.bat` + one UI button -> every Amazon link becomes at most one eBay listing on the app's current target (Sandbox -> sandbox, Production -> live). **Bar:** `docs/sprint2-bar-v3.md`. **Consolidation:** `docs/sprint2-planning-consolidation-2026-10-19.md`.

## Roles
Planner/driver/integrator: this session (never builds). Builder: codex. Tester: deepcode. Reviewer: opus. Critic: deepseek.

## Cards
| card | what | size | dep |
|---|---|---|---|
| T0 | register: fixture (20 lines, E=12), expected states per run, price snapshot, baseline census (incl. DD-SMOKE-TEST-1), control listing IDs, SKU->ASIN rule, receipt contract, `sprint2-freeze.json` | M | - |
| T1 | reader + durable run/row ledger, alias dedupe, resumable | S | T0 |
| T2 | pipeline worker: analyse -> margin -> draft -> stage -> publish, sequential background job, continue on error, single-flight lock | M | T1 |
| T3 | duplicate reconciliation: remote check across SKUs, adopt/resume existing offers, unknown outcome blocks resend | M | T2 |
| T4 | target pin + live gate: snapshot env, abort on switch, server-side `LIVE <n>` bound to file hash, cap, interception tests | M | T2 |
| T5 | UI + start.bat: one button, progress table, reattach after reload, env banner, actionable errors | M | T2 |
| T6 | measurement: runs A/B on the 20-line fixture, run C on the C-set, controls C1-C6, one receipt | M | T3-T5 |
| T7 | independent review (opus) and critic (deepseek) of receipt, dedupe, gate | S | T6 |
| REVIEW | sprint review | S | T7 |

**Not in this sprint:** first real live listing, variation groups, near-duplicate product detection, scale beyond 20 rows, profitability.

## Plan changes (append-only)
- 2026-10-19 (vote r1, 0 of 5 approvals; deepseek returned tool-call text only, no vote): bar v2 - commitment freeze vs measurement freeze + source SHA pin (codex, deepcode, sol, +); C5 passes with zero outbound requests, per-control evidence (codex, sol); run C non-vacuous with kill after remote accept and before durable ack (codex, sol, luna); executable census: baseline incl. smoke listing, SKU->ASIN rule + `ASIN:` marker, control listing IDs (deepcode, opus, luna); exact expectations enum + price snapshot (deepcode); C6 fails closed, sandbox-only claim (luna).
- 2026-10-19 (vote r2: 2 approvals sol, luna; 4 request changes): bar v3 - run C becomes a separate C-set scenario (4 ASINs) with deterministic fault-injection kill (deepcode, opus, deepseek); price-flip precedence with worked cases (codex); per-run deadline 20 min and price-snapshot method (deepcode); p counted from the run-A census, C6 runs as interception test (opus); census-anchored baseline classification (deepseek); C5 hard network deny (deepseek).
