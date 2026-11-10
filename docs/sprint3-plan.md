# Sprint 3 plan (DRAFT 2026-11-10) - list through the eBay web form, browser out of the way

Repos in this sprint: ai_dropshipping

**Status: v2 after planning round 1 (see sprint3-planning-consolidation-2026-11-10.md). Not voted, not frozen.** Sprint 2 is not closed (no review/retro yet) and the Sprint-create
ceremony (seat proposals, rating round, commitment vote, operator freeze) has NOT been run. Nothing here is executed.

## Why
The API listing path fails at publish with errorId 25019 / `BLOCK_Seller_NonBlackbird_Issue607` (ref 1234519) for account
butterflypro. The web listing form works (item 800851564584 listed by hand). Only eBay can lift the API block (ticket open).

## Goal (operator, 2026-11-10)
Fully automatic path to a live item through the eBay web form: draft in the app -> form filled in a real Chrome with its
own profile -> read back and verified -> submitted only after typed `LIVE n`.

## Browser rule (operator)
Own dedicated Chrome profile (`data/browser_profile/`), window created off-screen (`--window-position=-32000,-32000`),
never takes focus, never touches the operator's own browser. Real Chrome (`channel="chrome"`), not bundled Chromium
(Amazon already resets the bundled one, see delta d1). Login: the operator logs in ONCE by hand in that profile
(`tools/browser_login.py`); the robot never sees or types a password; if the session is gone it stops and says so.

## Registered bar (proposal)
- Dry run on >= 10 real drafts: form completely filled, every field read back FROM eBay's own review/preview page after a fresh reload (independent of the filler) equals the draft (title, category, price,
  quantity, condition, item specifics, photos count, policies), 0 mismatches ignored, screenshot per item. No live write.
- Browser unattended: during a 10-item run the operator's foreground window changes 0 times (measured by title sampling).
- Failure even if all tasks are done: any field filled with a value not provable from the draft.
- Drafts autosaved by eBay during dry runs are deleted afterwards; `submit_clicks = 0`; result line in `data/browser_runs.jsonl`.
- Foreground events of our Chrome = 0 (SetWinEventHook + GetForegroundWindow sampling, Notepad-in-front test).
- First live submit = separate operator decision, recorded as the first real use (Rule 10).

## Safeguards (live path built, behind the gate)
Flags `EBAY_LIVE_UPLOAD_ENABLED` + allow list + typed `LIVE n` + batch cap + audit `data/live_audit.jsonl`; no retries after
the submit click; one worker; stop at first mismatch, captcha, login prompt, or unexpected page.

## Tasks
| id | task | size | note |
|---|---|---|---|
| B0b | **FIRST GATE (1 h):** Seller Hub CSV upload as unpublished draft + ask the open support ticket whether the block covers it. Works and avoids 25019 -> cancel B1-B5 | S | needs operator |
| B0 | Spike (only if B0b fails and operator signs off on account risk in writing): persistent Chrome profile, off-screen window, session check, map the sell/create form (read-only, nothing submitted) | S | needs operator's one-time login |
| B1 | Launcher + session guard (focus-free, profile lock, kill on exit) | M | |
| B2 | Form filler from draft (reuses verified category/aspects, fail closed) | M | |
| B3 | Read-back verifier + screenshots + audit | M | |
| B4 | Gated submit (LIVE n, allow list, cap, no retry) | M | one-way door: L ceremony |
| B5 | UI: choose "Browser" path, single-worker queue, progress, resume | M | |
| B6 | Independent review (other model family) of B1-B5 | - | builder never reviews |

## Operator decision before any robot code
Written acceptance of the ToS/account risk (or fallback: robot fills and verifies, operator clicks submit by hand). Headless is not used.

## Risks (honest)
1. eBay user agreement restricts automated access to the site; the account already carries a restriction. A robot can get
   butterflypro limited further. Unmeasured; the operator accepts or declines this.
2. Bot detection / captcha: will not be solved or bypassed; the run stops.
3. The web form changes without notice; every selector needs a read-back check, drift = stop.
4. No sandbox for the web form: the only real test is a live listing, hence dry-run bar + operator-owned first live item.
5. Possible shortcut not yet tested: Seller Hub file upload (CSV). Spike B0b, 1 hour, may make the robot unnecessary.

## Mechanisms (Rule 10)
Browser runner: consumer = operator via UI button; trigger = button / start.bat; liveness = `data/live_audit.jsonl` and
`data/browser_runs.jsonl` lines, max age = last run.
