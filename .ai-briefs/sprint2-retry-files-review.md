# Review (opus, ask): branch s2-retry-files, worktree M:\ai_tmp\wt-s2-retry, `git diff main...HEAD`. Build brief: `.ai-briefs/sprint2-retry-files-build.md`.
Driver verified: 212 pytest passed, npm build ok, npm test 3 pass. Find what only running shows.
1. File choice security: bare names only. Probe `../x.txt`, `..\x.txt`, `C:\x.txt`, `/etc/x.txt`, `sub/x.txt`, `x.csv`, directory named x.txt, symlink/junction pointing outside, trailing dot/space, alternate data stream `a.txt:b`, case variants, very long, unicode; on the preview, start AND files endpoints; confirm no read/mkdir occurs outside upload_items.
2. Retry: only AMAZON_UNREACHABLE retried; Stop honoured during the pause (~1 s); abort/target change ends retrying; systemic cap still aborts the run; attempts/duration per attempt; no row processed twice in one pass; a row that succeeded on retry never produces a second eBay write; publish mode retry cannot publish an item whose price re-check fails; run total/counters correct (done counts, summary averages).
3. Single-flight and sandbox pin unchanged; production still refused.
4. UI (read App.tsx): dropdown, localStorage try/catch, attempts display, running file name, nothing sends a wrong file.
5. Run at least 6 mutants of your own against the new tests; list survivors.
Reply: findings ranked with evidence; end VERDICT: PASS | PASS-WITH-FIX | BLOCK. Do not modify project files.
