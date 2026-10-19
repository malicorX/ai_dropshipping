Repos in this sprint: ai_dropshipping

# Sprint 2 plan (PLANNED, NOT FROZEN; commitment vote r7 UNANIMOUS 6/6) - 2026-10-19

**Goal:** `upload_items/upload_items.txt` + `start.bat` + one UI button -> every Amazon link becomes at most one eBay listing on the app's current target (Sandbox -> sandbox, Production -> live). **Bar:** `docs/sprint2-bar-v7.md`. **Consolidation:** `docs/sprint2-planning-consolidation-2026-10-19.md`.

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
- 2026-10-19 (vote r3: 5 approvals codex, deepcode, opus, sol, luna; deepseek REQUEST-CHANGES): bar v4 - C-set artifacts frozen in sprint2-freeze.json; C1 restated for ERROR_RETRYABLE rows (deepseek); C5 exercises both refusal subcases and is deny-by-default (deepseek, deepcode); C-set all expected PUBLISHED, price-flip rule covers the C-set, C2 compares offerId and listingId from the after-kill census (opus, deepcode).
- 2026-10-19 (vote r4: 5 approvals codex, deepcode, deepseek, sol, luna; opus REQUEST-CHANGES): bar v5 - run B expectation depends on run A for ERROR_RETRYABLE rows (opus); run C wording uses offerId and listingId (opus); sandbox identity pin, per-segment run C clock, C5 authorized-path log, two after-kill reads >= 60 s apart (deepcode, deepseek, non-blocking).
- 2026-10-19 (vote r5: 5 approvals codex, opus, deepseek, sol, luna; deepcode REQUEST-CHANGES): bar v6 - C1: exactly one offer per ASIN across A and B, remote read before any retry, adopt not republish (deepcode); price-flip exemption inlined in verdict rule 1 (deepcode); control listing registers SKU + offerId + listingId, run C restart uses the same SHA (opus, non-blocking).
- 2026-10-19 (vote r6: 3 approvals opus, deepseek, luna; codex, sol, deepcode REQUEST-CHANGES): bar v7 - C1 'at most one offer per ASIN across A and B, exactly one if PUBLISHED' (codex, sol); rule 1 'more than one offer, or more than one item' (deepcode); UNKNOWN from an ambiguous pre-retry read lowers p, not NOT_MET (deepcode); p excludes price-flipped rows, counted from the run-A census (deepcode); receipt shows accepted offerId + pending count before kill and snapshot-to-run-A gap (opus, deepseek).
- 2026-10-19 (vote r7, unanimous, editorial only after the vote): clarification from opus's optional note, no change of meaning: p is judged on the run-A census alone; a row's local state (for example UNKNOWN) is not consulted. Disclosed here; the operator may ask for a confirming round before freezing.
