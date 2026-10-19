# Round 2 (deepcode), worktree branch s2-mark. Only tests/test_upload_items.py (+ one comment in ui/src/App.tsx). Heartbeat `_heartbeat.txt`.
Reviewer (opus) PASS-WITH-FIX: add tests that kill three surviving mutants, RED = show each mutant passes the old suite is NOT needed; show each mutant now FAILS:
M3: a saved listing state with status `unpublished` (staged, never published) must NOT be marked 'haben wir schon': the row is fetched/processed and published. Mutant: `published_listing_state` accepts any non-empty state.
M4: the final re-check before stage: a stub where the first check passes (not published) and the state becomes published between fetch and stage -> row ends skipped_existing with 0 stage calls. Mutant: remove the final re-check.
M5: old-style record: sandbox state file whose stored env says `production` is NOT marked for a sandbox run. Mutant: remove the env comparison.
Also fix the misleading comment near App.tsx ~1524 about the preview refresh (make the comment match the code). Full suite green, `npm run build` ok.
