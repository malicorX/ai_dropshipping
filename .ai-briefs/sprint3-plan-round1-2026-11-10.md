# Sprint 3 planning brief 1 (2026-11-10) - ai_dropshipping

You are a planning seat. Answer in <=350 words, plain text. Read docs/sprint3-plan.md (the driver's draft) in the repo if you have file access; the essentials are inlined here.

## Situation
App: Amazon.de link -> eBay.de listing (FastAPI + SQLite + React; Python, Playwright already used for Amazon fetch via installed Chrome, channel="chrome"). The eBay Inventory API publish fails for the production account with errorId 25019 / BLOCK_Seller_NonBlackbird_Issue607 (German tax rules block for non-web-form listing flows). A listing made by hand in the eBay web form works. Only eBay can lift the block (support ticket open, no answer yet).

## Operator goal (2026-11-10)
Fully automatic path to a live item through the eBay WEB listing form, driven from the app: draft -> form filled in real Chrome with its OWN profile (data/browser_profile/), window off-screen, never takes focus, operator's own browser untouched -> every field read back and compared to the draft -> submit only after a typed `LIVE n` (flags + allow list + batch cap + audit log; no retries after the submit click). The operator logs in once by hand in that profile; the robot never types passwords; session lost = stop and say so.

## Hard constraints
- No Amazon purchase, ever. No live eBay write during a sprint measurement: the registered bar must be reachable without a live write (the web form has NO sandbox). The first live submit is a separate operator decision.
- Nothing invented: a form field is filled only from facts proven on the Amazon page, else left empty / "Keine Angabe". Category must fit.
- No captcha/bot-detection bypassing; a captcha or unexpected page = stop.
- Builder never reviews own work; reviewers other model family.

## Draft tasks
B0 spike (profile, off-screen window, session check, read-only map of the sell form; also 1h check whether Seller Hub CSV file upload avoids the tax block), B1 launcher+session guard, B2 form filler, B3 read-back verifier+screenshots+audit, B4 gated submit, B5 UI button+single-worker queue, B6 independent review.

## Your answer
1. ONE registered bar (run-artifact field / test / count) that decides met / not met without a live write; and what would make the sprint a FAILURE even if all tasks are done.
2. Your role (planner/builder/tester/reviewer/critic) and your tasks: definition of done, size S/M, dependencies.
3. The strongest objection to the whole approach (e.g. eBay ToS / account risk, form fragility, simpler alternative such as the Seller Hub CSV upload) and what you would do about it.
4. How to keep the off-screen browser from stealing focus on Windows, concretely (flags, launch method), and how to MEASURE it.
