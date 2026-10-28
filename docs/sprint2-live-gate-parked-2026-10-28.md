# Guarded LIVE path - PARKED (not merged), 2026-10-28

Branch: `s2-live-gate` (pushed to origin; worktree `M:\ai_tmp\wt-s2-live`). Specs: `.ai-briefs/sprint2-live-gate-build.md`, `-fix1.md`, `-fix2.md` (on the branch). Flag `EBAY_LIVE_UPLOAD_ENABLED` defaults to false; nothing live was ever written.

## Review history
| round | opus | codex (critic) |
|---|---|---|
| 1 | PASS-WITH-FIX | BLOCK |
| 2 | PASS-WITH-FIX | BLOCK |
| 3 | BLOCK (one reproducible production publish via the legacy single-listing endpoint, fake transport) | no answer (`Selected model is at capacity`) - absence, not approval |

Tests on the branch at fix2: 363 passed with and without a fail-closed .env; npm build ok; npm test 8 pass.

## What is left (opus round 3, `...\runs\20261028_125715_22fb\response.md`)
1. BLOCK: `api.py` legacy stage/publish read `config.ebay_env()` for the 403 check, then `_require_ebay_sell`, then capture the env for `ebay_operation` - a target switch in between reaches production without any gate. Fix: capture env first, `with config.ebay_operation(env) as op_env:` and check production INSIDE; set the sandbox pin during legacy calls; add a publish-route wrapper test (mutant M14) and a race test.
2. Fail-closed `.env` is too strict for sandbox: drop the quote-count heuristic, catch `UnicodeDecodeError`/`ValueError`, apply "malformed means closed" only to the three gate keys.
3. Tests to kill: N13 (successful start consumes the nonce), N17 (audit price from staged state), N19 (`access_token()` record-env check), N12 (nonce TTL), M13 (`_live_env_seen` at import). OAuth callback: pass `env=callback_env` to `exchange_code`.
Also needed before any merge: a critic from a family other than deepcode's that actually answers (codex was at capacity), then Rule 4 steps.

## Direction check (Rule 8, self-assessment)
Proven: the sandbox flow (prepare / overview / publish / retry / file choice) is on main and measured. Not proven: the live path - three review rounds each found new races because the eBay environment is a mutable global; the S1 freeze fixed most of them. Decision: WEITER but parked; the operator does not want live listings today, and production stays refused on main. Next bounded step: one fix packet for items 1-3 and a final review round from opus + one other family; if that is not PASS from both, drop the live path and keep production permanently refused.
