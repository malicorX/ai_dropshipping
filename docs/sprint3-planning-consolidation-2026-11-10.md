# Sprint 3 planning consolidation (2026-11-10)

Roster used: deepcode, deepseek, gpt6-luna-max, gpt61-sol, opus. codex: first job failed on a malformed job file (driver error), re-submitted as `-r2`, no answer yet (recorded as absent). Skipped: Fable (banned), kimi/grok. Briefs: `.ai-briefs/sprint3-plan-round1-2026-11-10.md`.

## Convergence (all 5 seats)
1. **ToS/account risk is the strongest objection** (eBay user agreement restricts automated access; butterflypro already restricted; losing it is worse than the 25019 block). The `LIVE n` gate protects against accidents, not against this risk.
2. **B0b (Seller Hub CSV upload, eBay's own bulk path) becomes the FIRST gate**, 1 hour, before any robot code. If it works and avoids 25019, B1-B5 are cancelled. Also ask in the open support ticket whether the block covers file upload. (luna: ask eBay for written guidance on automation.)
3. **Bar**: one line in `data/browser_runs.jsonl`: dry run on >= 10 real drafts, readback mismatches 0, unproven fields 0, submit clicks 0, our foreground events 0, one screenshot per item.
4. **Read-back must be independent of the filler**: read eBay's own review/preview page after a fresh reload, not the values the robot typed (deepcode, opus). Otherwise agreement is vacuous.
5. **Focus**: persistent context, `channel="chrome"`, headed, `--window-position=-32000,-32000`, no `bring_to_front()`, photos via `set_input_files`, launch from the worker not the foreground console; measured by `SetWinEventHook(EVENT_SYSTEM_FOREGROUND)` plus 100-250 ms `GetForegroundWindow` sampling, matched by PID of the Chrome with `browser_profile` in its command line; Notepad-in-front test. Headless is NOT used (it announces itself; hiding that would be bot-detection evasion) - consistent with the operator's choice.

## Single-seat points worth taking
- eBay autosaves drafts: "no live write" = nothing published; dry runs must delete their eBay drafts afterwards (opus).
- Rehearsal bar proves filling, not publishability; says so openly (gpt61-sol).
- Sprint fails if the artifact can only be produced by clicking submit, or the web form itself needs tax data we lack (deepseek).
- Ambiguous outcomes after the submit click stay UNKNOWN across restart, never resubmitted (gpt61-sol).
- Alternative fallback if the operator does not sign off on the account risk: robot fills and verifies, the operator clicks submit by hand (opus).
- Dedicated hidden desktop (CreateProcess lpDesktop) as a stronger isolation option (gpt61-sol): B1 spike decides; not required.

## Dissent / not taken
- None conflicting. deepseek's "armed but disarmed" run is folded into B4 tests.

## Roles proposed
All five asked for planner/critic/tester; **nobody volunteered as builder**. Builder: codex or deepcode (driver picks at dispatch); reviewers/critics must be a different family from the builder.
