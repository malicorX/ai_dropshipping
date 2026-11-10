# Sprint 3 plan v7 (2026-11-10) - list through the eBay web form, browser out of the way

Repos in this sprint: ai_dropshipping

**Status: v5 after vote r3 (codex, opus approve; deepcode, deepseek request-changes, applied; v4 after r2: 3 approve / 3 request-changes, applied; see sprint3-commitment-consolidation-2026-11-10.md). Not frozen.**
Open before freeze: operator decisions D1-D3 below; Sprint 2 has no review/retro yet (operator waives or closes it first).

## Why
API listing fails at publish with errorId 25019 / `BLOCK_Seller_NonBlackbird_Issue607` (ref 1234519) for account butterflypro.
The web form works (item 800851564584 by hand). Only eBay can lift the API block (support ticket open).

## Goal (operator, 2026-11-10)
Fully automatic path to a live item through the eBay web form: draft in the app -> real Chrome with its own profile ->
every field read back from eBay and compared -> submit only after typed `LIVE n`.

## Definitions (one wording, used everywhere)
- **Live write** = publish / activate / any submit click that makes an item visible. Forbidden during measurement.
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
| B0b | **FIRST GATE, 1 h:** Seller Hub CSV upload of ONE row as unpublished draft (needs D1), read back after fresh reload; ask the open support ticket whether the block covers CSV publish | S | `data/b0b_verdict.json` = PASS / FAIL / UNKNOWN (below) |
| B0 | Spike: profile, off-screen window, session check, read-only map of the sell form | S | only after B0b = FAIL and D2 file committed |
| B1 | Launcher + session guard + focus probe (`SetWinEventHook(EVENT_SYSTEM_FOREGROUND)` + `GetForegroundWindow` every 100 ms, by Chrome PID with `browser_profile` in its command line; Notepad-in-front test) | M | pytest counts foreground events by PID |
| B2 | Form filler from draft (verified category/aspects, fail closed, missing evidence blocks the run) | M | unit tests + dry run of 1 item |
| B3 | Independent read-back: fresh reload, read eBay's review page (`readback_sources: review_page, drafts_row`) and the Drafts row; provenance check (a field without its listed source-class key, or a required field left empty, fails; `amazon_page` fields need Amazon evidence, `rule_config` fields need the named rule/setting); screenshots; draft IDs captured at creation in the `browser_runs.jsonl` line; delete only those exact IDs (never by title/position), reload, record that 0 of them remain; click allowlist: only the listed non-submit buttons, named by the German labels on the form ("Vorschau", "Entwurf speichern"; P0 confirms the exact labels in B0) may be clicked, any other button counts as `submit_clicks`, a test fails on an unlisted click | M | `browser_runs.jsonl` line |
| B4 | Gated submit (one-way door, ceremony L): reuse `upload_items.py` confirmation/nonce machinery; the hash covers the verified field/image/policy payload and the target account; rejects same-count batch replacement, post-verification edits, stale/replayed confirmation; audit written BEFORE the click; no retry; an ambiguous outcome stays UNKNOWN across restart and is never resubmitted | M | acceptance test per rejection; "armed, then disarmed before click" run |
| B5 | UI: choose Browser path, single-worker queue, progress, resume | M | UI test |
| B6 | Independent review (opus) + critic (deepseek) of B1-B5 | - | verdicts on the exact commit SHA |

## B0b verdict (three outcomes, no silent pass)
- **PASS**: one unpublished draft survives a fresh reload with readable fields within 60 min AND support confirms in writing that CSV publish is not blocked. Verbatim rule: PASS requires `status == PASS` in `data/b0b_verdict.json`; UNKNOWN and FAIL both block; timeout or silence maps to UNKNOWN. The written support confirmation is stored on disk at `data/support/b0b_confirmation.txt` (not chat); no file = no PASS. A live publish, if the operator ever authorises one, is recorded outside B0b and cannot set its verdict. Then B0-B5 are cancelled and the CSV-branch bar applies.
- **FAIL**: upload impossible or draft unreadable -> go on to B0 (needs D2).
- **UNKNOWN**: draft-only success, or support silence. A draft does not show 25019 is avoided (the block fires at publish). UNKNOWN is not FAIL: stop and return to the operator. If support is silent for 7 days (from the day the question is sent), the operator is asked to choose: wait longer, accept D2 and go to B0, or manual operation only. There is no automatic default.
- **CSV-branch bar** (if PASS): >= 10 drafts uploaded from app-generated CSV, read back from the Seller Hub Drafts page, 0 mismatches, 0 unproven fields.

## Registered bar (robot branch)
One line in `data/browser_runs.jsonl`: >= 10 real drafts in a no-submit run; `readback_mismatch = 0`; `unproven_fields = 0`; `submit_clicks = 0`; `foreground_events_ours = 0`; one screenshot per item; `readback_sources = review_page,drafts_row` (both required per line); drafts deleted afterwards.
**FAIL even if every task is done:** a filled value without its listed key in the per-field source-class table (Definitions), or a required field left empty; any submit click during measurement; a read-back that only echoes typed values; the robot triggers an account restriction.
It proves filling and persistence, not publishability and not source truth. The first live submit is a separate operator decision and is the first real use (Rule 10).

## Freeze gate (mechanical)
`tools/sprint3_freeze_check.py` (P0) parses `docs/sprint3-decisions.md`; pinned line format `D<n> | value | YYYY-MM-DD` for n = 1,2,3; exits non-zero on a missing/malformed line, D1 not in {`allowed`,`denied`}, D2 not in {`accepted`,`declined`,`after-b0b`}, D3 not in {`waived`,`closed`}; D1 `denied` blocks every browser task AND B0b; D2 `declined` blocks every browser task; D2 `after-b0b` permits B0b only when D1 = `allowed`; when D2 = `accepted` the check also fails if `docs/sprint3-risk-acceptance.md` is missing. It is run by `pytest` (so every landing runs it once the file exists as a gate) and by B0/B1 start-up. P0 done-when: a pytest seeds a deleted/garbled D-line and asserts non-zero exit. The check proves the decisions are present; it does not prove the robot is safe.

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
