# Sprint 3 commitment vote r1 (2026-11-10) - ai_dropshipping

Voting seat. Answer <=250 words, plain text. The package is docs/sprint3-plan.md (v2) with docs/sprint3-planning-consolidation-2026-11-10.md; inlined essentials:

Goal: fully automatic path to a live eBay item through the eBay WEB form (API listing is blocked by eBay account-level error 25019), in a dedicated Chrome profile, window off-screen, no focus steal, typed `LIVE n` before any submit. No Amazon purchase ever; no live eBay write during measurement.
Order: **B0b first gate (1 h)**: Seller Hub CSV upload as unpublished draft + ask support whether the block covers it; if it works, B1-B5 are cancelled. Only if B0b fails AND the operator signs the ToS/account risk in writing: B0 spike, B1 launcher+session guard+focus probe, B2 form filler, B3 independent read-back (from eBay's review page after reload) + screenshots + audit + draft cleanup, B4 gated submit (LIVE n, allow list, cap, no retry, UNKNOWN stays UNKNOWN), B5 UI + single-worker queue, B6 independent review (other family than builder).
Registered bar: `data/browser_runs.jsonl` line: >=10 real drafts, readback mismatch 0, unproven fields 0, submit clicks 0, our foreground events 0, screenshot per item. FAIL even if all tasks done: any value not proven on the Amazon page; submit click during measurement; read-back that only echoes typed values; account restriction caused by the robot.
Builder: not yet assigned (nobody volunteered); driver picks codex or deepcode at dispatch; reviewers/critics other family.
Honest disclosure: nothing of this is built or executed; only the plan docs are committed (236db2a).

Answer:
1. `VOTE: APPROVE-AS-IS | REQUEST-CHANGES | REJECT`
2. At most 3 exact, checkable changes, each with a done condition, and which one would move you to APPROVE-AS-IS.
3. The one risk left even if approved.
4. Is anything already executed a problem for freezing? (one sentence)
