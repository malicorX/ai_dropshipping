# Sprint 3 card S3-B0 (issue #40) - build brief (builder: codex) - ai_dropshipping

Work ONLY in this worktree (branch sprint3-b0). Do not push, do not touch main. Write `PARTIAL: <what is done>` into `_heartbeat.txt` once a minute (do not commit it, nor `_report.md`).
Read first: docs/sprint3-plan.md (Browser rule, B0 row, Definitions), docs/sprint3-field-sources.md, docs/sprint3-bar-v1.md. Playwright 1.57 and Chrome (`C:/Program Files/Google/Chrome/Application/chrome.exe`) are installed; use `channel="chrome"`, headed, `launch_persistent_context`.

## Hard rules (a violation fails the card)
- NEVER type or handle a password; NEVER click submit/publish/"Einstellen"/"Angebot einstellen"; NEVER fill or change any form field; NEVER create or delete anything on eBay. B0 is READ-ONLY.
- Never call `bring_to_front()`. Window starts at `--window-position=-32000,-32000`. No headless.
- Profile dir `data/browser_profile/` (data/ is not committed; make sure it is git-ignored, do not commit it).
- No change outside `tools/`, `tests/`, `docs/sprint3-b0-*.md`, `.gitignore`. Nothing existing in `dropship_desk/` is modified.

## Deliverables
1. `tools/browser_login.py`: opens the SAME profile with a VISIBLE on-screen window (position 100,100) at https://www.ebay.de, so the operator logs in by hand once; waits until the window is closed by the operator; prints where the profile lives. No credential handling at all.
2. `tools/browser_spike.py` (read-only): launches the profile off-screen; (a) session check: open https://www.ebay.de/sh/ovw (Seller Hub) and decide LOGGED_IN / LOGGED_OUT from page evidence (URL redirected to signin = logged out); if logged out, exit code 3 with the message "bitte tools/browser_login.py ausfuehren"; (b) read-only form map: open the eBay sell entry (https://www.ebay.de/sl/sell) and walk only via navigation to the listing form WITHOUT typing into it (stop at the first page that shows the form, or document where it stops); dump to `data/b0_form_map.json`: URL path (no query secrets), every visible button/link label (exact German text), field labels with input type and required flag; (c) window evidence: record `window.screenX/screenY` (must be off-screen) and write a screenshot to `data/b0_shots/`. Output also pins the exact German labels of "Vorschau" and "Entwurf speichern" (or the real ones) into a list `click_allowlist_candidates` in the JSON; if not found, say so, do not guess.
3. `tests/test_browser_spike.py`: pure unit tests with a fake page object (no real browser, no network): session decision logic, JSON map shape, "no click, no fill, no bring_to_front is ever called" (the fake page raises if `click`, `fill`, `type`, `bring_to_front`, `press` is called), exit code 3 when logged out. RED first: run against an empty tool and paste the failure into `_report.md`. List two single-line mutants you tried (e.g. call `page.click`, drop the logged-out exit) and that the tests fail on each.
4. `docs/sprint3-b0-notes.md`: how the operator runs the login, what the spike does, known limits. Full suite (`python -m pytest -q`) result pasted into `_report.md`.

## Not in B0
Launcher/focus probe (B1), filling (B2), read-back (B3), submit (B4). Do not run the spike against real eBay yourself; the driver does that after the operator's login.
