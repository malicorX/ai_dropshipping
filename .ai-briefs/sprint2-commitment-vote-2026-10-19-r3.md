# Sprint 2 commitment vote r3 (2026-10-19) - ai_dropshipping

You are a voting seat. Answer in <=250 words, plain text, no tool calls unless you must read a file. Round 2: sol and luna APPROVED-AS-IS; codex, deepcode, opus, deepseek requested changes. All their requested changes are applied in bar v3 below (see the plan's "Plan changes"): run C is now a separate C-set scenario with a deterministic kill, price-flip precedence has worked cases, per-run deadline, p counted from the run-A census, census-anchored classification, C5 hard network deny. Nothing executed (no card started); smoke listing DD-SMOKE-TEST-1 is registered as baseline.

Questions:
1. `VOTE: APPROVE-AS-IS | REQUEST-CHANGES | REJECT`
2. At most 3 exact, checkable changes, each with a done condition, and which change would move you to APPROVE-AS-IS.
3. The one risk left even if approved.
4. Is anything already executed a problem for freezing? (one sentence)

---- PLAN ----
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

---- BAR v3 ----
# Sprint 2 registered bar v3 (2026-10-19, after vote round 2) - NOT frozen

**Little north star:** the operator drops `upload_items.txt` (Amazon.de links) into `upload_items/`, starts the app with `start.bat`, clicks ONE button, and every link becomes at most one eBay listing on the target the app is set to (Sandbox -> sandbox eBay, Production -> live eBay), without duplicates.

## Two freeze points (changed in v2)
1. **Commitment freeze** (operator's freeze): plan, this bar, card list. Implementation T1-T5 happens AFTER it; that is not a violation.
2. **Measurement freeze**, written by T0/T6 as `sprint2-freeze.json` before run A: tested source SHA (clean worktree), fixture SHA, expected-table SHA, baseline-census SHA, price-snapshot SHA. A pre-run check exits 0 at that SHA and nonzero after a one-byte edit. Any change to those files, or to source between runs A and C, is INCONCLUSIVE (rule 2). The receipt records both freeze points.

## Fixture and registration (S2-T0; all committed before the measurement freeze)
- 20 lines from `bulk/000001.txt`: 12 distinct expected-publishable ASINs (E = 12), 3 alias/repeat lines of E ASINs, 2 junk lines, 2 margin-FAIL ASINs, 1 control ASIN that already has a published sandbox listing. |E| < 10 registered = INCONCLUSIVE.
- **C-set (run C only, outside E and p):** a second registered file of 4 distinct ASINs, disjoint from the 20 lines, with its own expected states. The census before run C shows zero C-set offers/items.
- A terminal-state/reason enum, and per line `expected_state` + `expected_reason` for runs A, B and C separately.
- **Price snapshot:** the Amazon price/availability used for each row's margin decision, recorded per ASIN with fetch timestamp, host and field; the receipt prints snapshot vs runtime price for every row. A row whose margin outcome flips relative to the snapshot is a *price-flipped row*: its state/reason difference is exempt from the mismatch check in verdict rule 1, it receives no success credit in p, and the original |E| stays the denominator. Up to 2 flipped rows are tolerated; 3 or more make the measurement INCONCLUSIVE unless a higher-priority violation exists. A duplicate, production request, purchase or unknown offer is NOT_MET regardless of flips. Worked cases for E=12 (MET needs p >= 10): 0 flips and p=10 MET; 2 flips and p=10 MET; 2 flips and p=9 WEAK; 3 flips INCONCLUSIVE; 1 flip plus a duplicate NOT_MET.
- **Baseline census (hashed):** all remote sandbox inventory items and offers, paginated, for every SKU, taken before run A. It includes the smoke listing `DD-SMOKE-TEST-1` (`tools/sandbox_smoke.py`) and the control listing.
- **Control listing:** T0 creates it (or names an existing one) and registers its offerId and itemId. It is tied to the control ASIN.
- **SKU -> ASIN rule:** SKU `DD-<ASIN>` maps to that ASIN. The app also writes the marker `ASIN:<ASIN>` into the inventory item description, so an offer under any other SKU is attributable. Classification is census-anchored: **baseline** = any offerId/itemId present in the hashed pre-run census regardless of its SKU (the smoke listing `DD-SMOKE-TEST-1` need not follow `DD-<ASIN>`); E / control / C-set = attributed by the SKU rule or the marker; **unknown** = absent from the census and unattributable. A unit test with three remote offers (E, control, non-DD baseline) yields zero unknown and zero duplicate flags; an injected unregistered offer yields unknown. A test with an alternate-SKU fixture proves an injected second offer for an E ASIN is detected.

## Measurement (Sandbox only; the first live use is a separate operator decision)
Start with a clean sandbox for E (census shows zero E offers/items). Launch through `start.bat`, click once (**run A**), click again after completion (**run B**, identical re-click), and **run C** below. After each run wait >= 60 s and read the remote sandbox state twice (paginated census, not local files); the two reads must be identical. Receipt `sprint2-run.json`: both freeze points, per-row state, request hosts, timestamps, remote offer/item IDs, the census classification.

**Run C (separate scenario on the C-set, no reset of E):** the app is started with a deterministic fault-injection flag that hard-exits in the window after a remote publish is accepted and before its durable local acknowledgement. The kill happens after at least one C-set publish is accepted with other C-set rows still pending (receipt: flag, exit code, timestamps, pending-row count > 0). Restart and resume. The census after resume must show, for every C-set ASIN, exactly one offer/item, and the offerId of the killed row equal to its pre-kill offerId. The receipt records the census before run C (zero C-set offers), after the kill and after resume.

**Deadline:** each run has a registered wall-clock limit of 20 minutes (frozen in `sprint2-freeze.json`). Exceeding it is NOT_MET, with the pending-row state dumped to the receipt.

**p is counted from the run-A census** (after the settle wait and two identical reads). Runs B and C are judged by their own controls.

## Verdict (top to bottom, first match wins)
1. NOT_MET on any: actual request to a production eBay host (a refused or intercepted attempt that sends no outbound request is not one); Amazon cart/purchase action; an ASIN with more than one offer or item across all SKUs (per the SKU->ASIN rule); an offer classified `unknown`; a row whose state or reason differs from its registered expectation for that run (an ordinary E row ending `ERROR_RETRYABLE` only lowers p); a failed control below.
2. INCONCLUSIVE if no violation is seen but: |E| < 10; a frozen file or source SHA changed after the measurement freeze or between runs A and C; the duplicate claim rests only on local files or mocks; two remote reads differ; a required scenario never exercised its action (a publishing scenario with zero publish requests; C5 is judged by rule C5 below, not by this clause); price flips as above.
3. Otherwise p = number of E targets with a published sandbox item: p >= ceil(0.8 |E|) MET; ceil(0.6 |E|) <= p < ceil(0.8 |E|) WEAK; anything else NOT_MET.

## Required controls (outside E and p)
- C1 run B creates 0 new offers/items.
- C2 run C: every C-set row accounted for, exactly one offer/item per C-set ASIN, the killed row's offerId unchanged across the kill, 0 duplicates.
- C3 the control ASIN is skipped; its offer/item IDs unchanged.
- C4 a concurrent second click while a run is active is refused (HTTP 409) or attaches to the same run; 0 extra writes.
- C5 Production gate, by interception (no real request): the run request is submitted, the server refuses it (target Production without both flags, or without the server-side `LIVE <n>` confirmation bound to the file hash), and the interception log shows 0 outbound calls; the authorized path is exercised through interception up to the point just before the network; switching the target during a run aborts the run. C5 uses a hard network deny: the interception layer patches the HTTP client so any call to a production eBay host raises, and the log shows 0 outbound production calls. C5 passes with zero outbound requests.
- C6 an injected ambiguous publish outcome (timeout) keeps the row UNKNOWN until an authoritative remote read; the request log shows no second publish before reconciliation. Fails closed under delayed visibility. C6 runs as an interception test against the app's eBay client with the injected timeout; it never changes the A/B/C census.

## Live path rules (built in this sprint, used only by operator decision)
Target snapshot per run; Production requires `EBAY_AUTOMATION_ENABLED`, `EBAY_ALLOW_LIST`, and a typed `LIVE <n>` confirmation showing seller, count, file hash; live batch cap `EBAY_LIVE_BATCH_MAX` (default 10, larger files run the first 10 and ask again); stop after 3 consecutive eBay errors; missing/negative margin never publishes.

## Not claimed
Sandbox success is not live behaviour: this sprint proves sandbox behaviour and an intercepted Production gate only. Not claimed: profitability, Amazon data rights, live seller-account behaviour, listing quality at scale, scale beyond 20 rows, variation-group publishing, price stability beyond the snapshot.
