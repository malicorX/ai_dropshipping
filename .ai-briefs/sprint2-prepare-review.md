# Review (opus, ask): branch s2-prepare, worktree M:\ai_tmp\wt-s2-prepare. Diff: `git diff main...HEAD`. Brief of the build: `.ai-briefs/sprint2-prepare-build.md`.
Driver verified: 173 pytest passed, `npm run build` ok, `npm test` 3 pass. Do not just repeat that.
Find defects only obtainable by running/mutating. Priorities:
1. Can prepare mode touch eBay in ANY way (stage/publish/oauth/http)? Prove with a spy or mutation.
2. Can the publish batch put live an item whose price re-check failed, or one already published, or a variation parent? Can production ever be reached (endpoints, mid-run env flip, sandbox pin)?
3. list_prepared correctness: published excluded, unpublished-offer included, env separation (sandbox vs production state files), stale draft with changed price.
4. Single-flight: start/prepare/publish concurrently; stop; status "mode".
5. UI (`ui/src/App.tsx`): select all/none, count, disabled in production, refresh after run; anything that sends an empty or wrong asin list.
6. Run at least 5 mutants of your own against tests/test_prepared.py and report which survive.
Reply: findings ranked, each with the command/evidence; end with VERDICT: PASS | PASS-WITH-FIX | BLOCK. Do not modify project files.
