# Fix packet (builder deepcode), branch s2-retry-files, same worktree. Heartbeat `_heartbeat.txt`, report `_report.md`. Commit on the branch (not _heartbeat/_report), do not merge/push. Opus review findings, all to fix:
1. UI (App.tsx ~1722): the Upload table must show the PREVIEW of the selected file whenever no run is active or `status.file` differs from the selected file; only an active run (or the finished run of the SAME selected file) shows run rows.
2. Reject any `:` in the file name (`_invalid_name`): alternate data streams (`upload_items.txt:hid.txt`, `ab:c.txt`) read hidden data today. Tests for both names on preview, start and files (400, nothing read).
3. Tests for the pause: Stop, target change and a systemic abort during the retry pause must end the run within ~1.5 s with the real step size (use a pause constant of e.g. 30 and assert wall time < 1.5 s via a thread, or a patched clock) - this must kill: stop check removed from the pause loop, step 0.25s -> 3600s, target-change check removed.
4. UI: on load, if the remembered file no longer exists, do not request its preview (wait for /files, then fall back to the default); a later successful preview clears the preview error.
5. `list_upload_files`: skip symlinks and reparse points (do not follow them for size/lines/mtime); add a test with a fake (monkeypatched `Path.is_symlink`) entry.
6. `_finalize_retry_reasons` must also run when a retry pass ends by Stop/abort/target change, so rows keep consistent "after N attempts:" reasons.
7. Retry only when the reason starts with `AMAZON_UNREACHABLE` followed by `:` or end (not `AMAZON_UNREACHABLE_NOT...`).
8. Fix the "never read" spy in the start-endpoint test so it patches `upload_items.read_upload_file` (what start calls) and really observes.
9. Whitespace-only `file` -> 400 `INVALID_UPLOAD_FILE`, not the default.
Rules: RED first for 2, 3, 5, 6, 7, 9; GREEN full `python -m pytest -q`; `npm run build` and `npm test` in ui/. No network; tests must never start a real Amazon fetch (stub the fetch in every start test, including those with odd file names). Do not touch .env, data/, upload_items/, docs/, dropship_desk/amazon/.
