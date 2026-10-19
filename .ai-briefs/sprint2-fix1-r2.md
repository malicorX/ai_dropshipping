# Fix packet 1, round 2 (deepcode), worktree branch s2-fix1. Heartbeat `_heartbeat.txt`, report `_report.md`.
Reviewer (opus) PASS-WITH-FIX:
(a) Add tests so these mutants FAIL: M1 case-sensitive variation-label check; M4 no duration set on the target-changed abort path; M8 no duration set on the run-abort error path (ChromeNotFound / failure-cap).
(b) `_candidate_ean`: match ONLY the exact keys `ean`, `EAN`, `gtin`, `GTIN` (no substring match: a key like `meaning_code` was taken as an EAN); accept only values of exactly 8, 12, 13 or 14 digits. Tests: exact key + 13 digits accepted; `meaning_code: "123456789"` rejected; 9-digit value rejected; real GTIN replaces 'Nicht zutreffend'.
(c) The UI summary 'average per processed item' must exclude rows skipped as 'haben wir schon' (and rows with no duration). Test or at least a pure helper unit test if the UI has none; `npm run build` ok.
Full suite green; show M1, M4, M8 now fail the suite (RED=mutant-fails evidence in `_report.md`).
