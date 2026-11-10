# Sprint 3 plan v10 (2026-11-10) - list through the eBay web form, browser out of the way

Repos in this sprint: ai_dropshipping

**Status: v10 after delta votes r7/r8 (history in sprint3-commitment-consolidation-2026-11-10.md). Not frozen.**
Open before freeze: operator decisions D1-D3 below; Sprint 2 has no review/retro yet (operator waives or closes it first).

## Why
API listing fails at publish with errorId 25019 / `BLOCK_Seller_NonBlackbird_Issue607` (ref 1234519) for account butterflypro.
The web form works (item 800851564584 by hand). Only eBay can lift the API block (support ticket open).

## Delta v8 (operator, 2026-11-10): first test = ONE item
Operator: for testing, just list a single one of the items that kept failing over the API. This replaces the 10-draft dry-run as the FIRST measurement
(the 10-item dry run stays as the later volume bar). Test item: **B0D87HWM4W** (API offer 330522494011 at 69.99; category already verified).
Sequence: (1) robot fills the form for that one item, reads back from eBay's review page and the Drafts row, 0 mismatches, 0 unproven fields, no submit;
(2) the operator reviews the screenshots and types `LIVE 1` for that exact verified payload (B4 binding); (3) one live item = the operator-owned live decision
and the first real use. One live item is therefore inside this sprint's measurement by the operator's order (supersedes the "no live write during measurement"
rule in SPRINT-PROCESS.md for exactly this one item); D1 `allowed` covers drafts only; the single live submit is governed solely by D4. D2 stays a separate written acceptance
(for the robot touching the account). B0b (CSV, 1 h) stays available but is no longer a precondition if the operator accepts D2.

## Goal (operator, 2026-11-10)
Fully automatic path to a live item through the eBay web form: draft in the app -> real Chrome with its own profile ->
every field read back from eBay and compared -> submit only after typed `LIVE n`.

## Definitions (one wording, used everywhere)
- **Live write** = publish / activate / any submit click that makes an item visible. Forbidden during the `draft_bar` measurement. The ONLY exception is the single D4 live probe (below): exactly one B0D87HWM4W submit, bound to the post-read-back audited payload hash; a second or unbound submit = FAIL.
- **Draft** = unpublished item eBay stores (autosave). Creating drafts in the production account needs operator decision D1.
- **Source class** of every field is one of two, and each has a listed key. **Unproven field** = a filled field without its listed key
  (the field is then left empty / "Keine Angabe" instead).
  - `amazon_page` (must trace to the Amazon page): title (`draft_title` from `amazon_title`), description (`description_html` rewritten from Amazon bullets, no unproven claim), item specifics (`aspects.resolve_aspects` evidence), condition (`condition`), photos (`images`: own re-encoded files, count + hash).
  - `rule_config` (comes from a recorded rule or setting, not from Amazon): category (`ebay_overrides.json` `category_id`, else `verified_listing_specifics` result), price (`price`, `margin.py` MarginSettings), quantity (`DEFAULT_QUANTITY` in `dropship_desk/ebay/listing.py`), policies (the policy ids in `data/ebay_production.json`). P0 pins the exact key of each in `sprint3-bar-v1.md`.
  - **A filled field absent from this table, or a required field left empty, = FAIL.**
  `docs/sprint3-bar-v1.md` (P0) carries the same table.

## Browser rule (operator)
Dedicated Chrome profile `data/browser_profile/`, real Chrome (`channel="chrome"`), headed but off-screen
(`--window-position=-32000,-32000`), no `bring_to_front()`, photos via `set_input_files`, started from the worker. Headless is NOT used
(it announces itself; hiding that would be bot-detection evasion). The operator logs in ONCE by hand; the robot never handles a
password; lost session = stop. The operator's own browser is never touched.

## Tasks, roles, order
Builder: **codex** (all B-cards). Reviewer for B1-B5: **opus** (other family). Critic: **deepseek**. Planner/tester seats: deepcode (bar schema, B0b memo),
gpt61-sol (B4 binding spec), gpt6-luna-max (provenance matrix). Integrator/driver: Claude (full suite, push, board). Builder never reviews.

| id | task | size | done when |
|---|---|---|---|
| P0 | Freeze the bar schema + provenance matrix (fields above, comparison rule per field) before any code | S | committed `docs/sprint3-bar-v1.md`, byte-identical bar text in plan and briefs |
| B0b | **FIRST GATE unless D2 = `accepted` (then optional, runs in parallel, verdicts still recorded), 1 h:** Seller Hub CSV upload of ONE row as unpublished draft (needs D1), read back after fresh reload; ask the open support ticket whether the block covers CSV publish | S | `data/b0b_verdict.json` = PASS / FAIL / UNKNOWN (below) |
| B0 | Spike: profile, off-screen window, session check, read-only map of the sell form | S | routing: D2 `accepted` -> B0 runs first, B0b optional; D2 `after-b0b` -> only after B0b = FAIL; the D2 file `docs/sprint3-risk-acceptance.md` must exist either way. The freeze-check tests enforce this routing |
| B1 | Launcher + session guard + focus probe (`SetWinEventHook(EVENT_SYSTEM_FOREGROUND)` + `GetForegroundWindow` every 100 ms, by Chrome PID with `browser_profile` in its command line; Notepad-in-front test) | M | pytest counts foreground events by PID |
| B2 | Form filler from draft (verified category/aspects, fail closed, missing evidence blocks the run) | M | unit tests + dry run of 1 item |
| B3 | Independent read-back: fresh reload, read eBay's review page (`readback_sources: review_page, drafts_row`) and the Drafts row; provenance check (a field without its listed source-class key, or a required field left empty, fails; `amazon_page` fields need Amazon evidence, `rule_config` fields need the named rule/setting); screenshots; draft IDs captured at creation in the `browser_runs.jsonl` line; delete only those exact IDs (never by title/position), reload, record that 0 of them remain; click allowlist: only the listed non-submit buttons, named by the German labels on the form ("Vorschau", "Entwurf speichern" expected; B0's form map pins the exact labels, and until they are pinned the allowlist is empty = no click is allowed, fail closed) may be clicked, any other button counts as `submit_clicks`, a test fails on an unlisted click | M | `browser_runs.jsonl` line |
| B4 | Gated submit (one-way door, ceremony L): reuse the typed-confirmation pattern of `upload_items.py` but with a NEW hash schema (today's `compute_batch_hash` covers only mode/env/ASINs and nonces are in memory): env, seller id, target account, eBay draft ID, all verified fields/images/policies, plus an ON-DISK arm / UNKNOWN record so a restart does not drop the state; the hash covers the verified field/image/policy payload and the target account; rejects same-count batch replacement, post-verification edits, stale/replayed confirmation; audit written BEFORE the click; no retry; an ambiguous outcome stays UNKNOWN across restart and is never resubmitted | M | acceptance test per rejection; "armed, then disarmed before click" run |
| B5 | UI: choose Browser path, single-worker queue, progress, resume | M | UI test |
| B6 | Independent review (opus) + critic (deepseek) of B1-B5 | - | verdicts on the exact commit SHA |

## B0b verdict (three outcomes, no silent pass)
- Scope: PASS-cancels and UNKNOWN-stops below bind only when D2 = `after-b0b`. When D2 = `accepted`, B0b outcomes are recorded but neither cancel nor block B0-B5. A PASS then ends the volume plan for the robot (CSV is chosen for volume); the D4 live probe still needs the operator to re-confirm D4 (ask).
- **PASS**: one unpublished draft survives a fresh reload with readable fields within 60 min AND support confirms in writing that CSV publish is not blocked. Verbatim rule: PASS requires `status == PASS` in `data/b0b_verdict.json`; UNKNOWN and FAIL both block; timeout or silence maps to UNKNOWN. The written support confirmation is stored on disk at `data/support/b0b_confirmation.txt` (not chat); no file = no PASS. A live publish, if the operator ever authorises one, is recorded outside B0b and cannot set its verdict. Then B0-B5 are cancelled and the CSV-branch bar applies.
- **FAIL**: upload impossible or draft unreadable -> go on to B0 (needs D2).
- **UNKNOWN**: draft-only success, or support silence. A draft does not show 25019 is avoided (the block fires at publish). UNKNOWN is not FAIL: stop and return to the operator. If support is silent for 7 days (from the day the question is sent), the operator is asked to choose: wait longer, accept D2 and go to B0, or manual operation only. There is no automatic default.
- **CSV-branch bar** (if PASS): >= 10 drafts uploaded from app-generated CSV, read back from the Seller Hub Drafts page, 0 mismatches, 0 unproven fields.

## Registered bar (robot branch)
Two separate record kinds in `data/browser_runs.jsonl`:
- `kind = live_probe` (D4, exactly one line, only B0D87HWM4W): fill, read-back 0 mismatches / 0 unproven fields, then ONE operator-typed `LIVE 1` submit; the typed confirmation carries the verified payload hash (reuse `upload_items.py` nonce machinery, hash over env, seller id, all verified fields/images/policies); the pre-click audit records the gate names from `config.live_write_gate_missing()` and the hash, and a closed gate aborts (test). The D4 draft is retained for the submit (not deleted by B3 cleanup). The submit is logged in `live_audit.jsonl` and is not counted in the draft bar.
- `kind = draft_bar`: >= 10 real drafts in a no-submit run; `readback_mismatch = 0`; `unproven_fields = 0`; `submit_clicks = 0`; `foreground_events_ours = 0`; one screenshot per item; `readback_sources = review_page,drafts_row` (both required per line); drafts deleted afterwards.
**FAIL even if every task is done:** a filled value without its listed key in the per-field source-class table (Definitions), or a required field left empty; any submit click during measurement; a read-back that only echoes typed values; the robot triggers an account restriction.
It proves filling and persistence, not publishability and not source truth. The first live submit is a separate operator decision and is the first real use (Rule 10).

## D4 live probe preconditions (all mechanical or recorded)
`config.live_write_gate_missing()` is re-read immediately before the click (a browser click bypasses the HTTP-level `ensure_write_target_allowed`); test: closing a gate between confirmation and click aborts. `LIVE 1` is accepted only when: freeze check exit 0 (incl. `D4 | live-1-B0D87HWM4W | <date>` line, which the check validates); B4 acceptance tests pass on the executed commit, incl. durable UNKNOWN across restart; opus has explicitly APPROVED B1-B5 (B6) on the exact executed SHA; REQUEST-CHANGES, REJECT, or a missing/stale verdict blocks `LIVE 1`; D2 = `accepted` and the risk-acceptance file exists. Zero read-back mismatches alone never enables the submit. `SPRINT-PROCESS.md` carries the matching one-line exception.

## Freeze gate (mechanical)
`tools/sprint3_freeze_check.py` (P0) parses `docs/sprint3-decisions.md`; pinned line format `D<n> | value | YYYY-MM-DD` for n = 1,2,3 and, as the sole allowed D4 form, exactly one line `D4 | live-1-B0D87HWM4W | YYYY-MM-DD` (ASIN must match; missing, duplicate, other value or malformed = non-zero exit; `LIVE 1` is refused without it; pytest for a malformed D4); exits non-zero on a missing/malformed line, D1 not in {`allowed`,`denied`}, D2 not in {`accepted`,`declined`,`after-b0b`}, D3 not in {`waived`,`closed`}; D1 means unpublished drafts only (live writes are expressed solely by D4, so `allowed` never authorises a submit); D1 `denied` blocks every browser task AND B0b; D2 `declined` blocks every browser task; D2 `after-b0b` permits B0b only when D1 = `allowed`; when D2 = `accepted` the check also fails if `docs/sprint3-risk-acceptance.md` is missing. It is run by `pytest` (so every landing runs it once the file exists as a gate) and by B0/B1 start-up. P0 done-when: a pytest seeds a deleted/garbled D-line and asserts non-zero exit. The check proves the decisions are present; it does not prove the robot is safe.

## Operator decisions needed before freeze
- **D1** Allow creating unpublished DRAFTS on the production account during Sprint 3 measurement (amends SPRINT-PROCESS.md "no live eBay write": live write is redefined as publish/submit). Without it the bar cannot be measured (the form has no sandbox).
- **D2** Written account-risk acceptance (committed file `docs/sprint3-risk-acceptance.md`, confirmed by the operator in chat) before ANY automated browser filling, including "robot fills, operator clicks submit" (manual submit does not remove the automated-access risk). Declined = manual operation only.
- **D3** Sprint 2: close with a short review, or explicitly waive it for Sprint 3.

## Risks (honest)
1. eBay's user agreement restricts automated access; butterflypro is already restricted; further restriction is unmeasurable and irreversible.
2. Captcha / bot detection: not bypassed, the run stops.
3. Form drift: every selector has a read-back check; drift = stop.
4. No sandbox for the form: dry-run bar + operator-owned first live item.

## Mechanisms (Rule 10)
Browser runner: consumer = operator via UI button; trigger = button / start.bat; liveness = `data/browser_runs.jsonl` + `data/live_audit.jsonl`, max age = last run.
