# Sprint 3 card S3-P0 - build brief (builder: codex) - ai_dropshipping

Work ONLY in this worktree (branch sprint3-p0). Do not push, do not touch main, do not touch any live/eBay code. Budget: small. Write a line `PARTIAL: <what is done>` into `_heartbeat.txt` once a minute; delete `_heartbeat.txt` and `_report.md` before finishing is NOT needed, but do not commit them.

Read first: docs/sprint3-plan.md (v13, sections Definitions, Freeze gate, D4 live probe preconditions, Registered bar) and docs/sprint3-decisions.md.

## Deliverables
1. `tools/sprint3_freeze_check.py` + `tests/test_sprint3_freeze_check.py`.
   - Parses `docs/sprint3-decisions.md` (path overridable by `--file`). Line format `D<n> | value | YYYY-MM-DD`.
   - DEFAULT mode: D1 in {allowed,denied}, D2 in {accepted,declined,after-b0b}, D3 in {waived,closed}, each exactly once, valid date; D4 absent allowed; a present D4 must be exactly `D4 | live-1-B0D87HWM4W | YYYY-MM-DD` and unique, else non-zero exit.
   - `--require-live` mode: additionally D4 must be present and valid, D1 == allowed, D2 == accepted, `docs/sprint3-risk-acceptance.md` must exist (path relative to the checked file's directory), and `data/b0b_verdict.json` (relative to repo root, `--root` overridable) must not exist with `"status": "PASS"`. Exit codes: 0 ok, 2 on any violation, with one stderr line per violation.
   - Routing checks from the plan: D1 denied -> report "blocks all browser tasks and B0b"; D2 declined -> "blocks all browser tasks"; D2 after-b0b -> note that only B0b is permitted. D2 accepted requires the risk file in DEFAULT mode too.
   - Tests (RED first: run them against an empty tool and paste the failure into _report.md): per mode and per case, incl. deleted D-line, garbled line, duplicate, D4 wrong ASIN, D4 absent in default (ok) and in --require-live (fail), missing risk file, b0b PASS blocks live.
2. `docs/sprint3-bar-v1.md`: the per-field source-class table with EXACT keys in this repo's code/data (read dropship_desk/models.py, dropship_desk/ebay/listing.py, aspects.py, taxonomy.py, data/ebay_production.json, the draft JSON written under data/): for each of title, description, item specifics, condition, photos, category, price, quantity, policies: source class (`amazon_page` or `rule_config`), the exact key/file/function, and the comparison rule for the read-back. Where a key does not exist, write `MISSING: <what>` - do not invent one. Then the bar text for `kind=live_probe` and `kind=draft_bar` copied BYTE-IDENTICAL from docs/sprint3-plan.md (Registered bar section).
3. Run the full suite (`python -m pytest -q`) in the worktree and paste the result into _report.md.

## Rules
Nothing invented. No change outside tools/, tests/, docs/sprint3-bar-v1.md. Mutants: for the tool, list two single-line mutations you tried (e.g. accept missing D2; ignore --require-live) and that the tests fail on each.
