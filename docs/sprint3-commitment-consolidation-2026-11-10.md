# Sprint 3 commitment vote consolidation

| round | seat | vote | main requests |
|---|---|---|---|
| r1 | codex | REQUEST-CHANGES | B0b outcomes explicit (draft != avoids 25019, silence = INCONCLUSIVE); risk acceptance for every automated path; one provenance wording |
| r1 | deepcode | REQUEST-CHANGES | draft creation contradicts "no live write" -> operator amendment; one bar text; builder named + B0b exit test |
| r1 | deepseek | REQUEST-CHANGES | name executor; live write = publish; readback_source + focus polling pinned |
| r1 | gpt61-sol | REQUEST-CHANGES | Amazon-page proof wording; remove unsigned fallback; B4 confirmation binding |
| r1 | opus | REQUEST-CHANGES | B0b PASS/FAIL/UNKNOWN; one proof wording; CSV-branch bar + risk sign-off file; Sprint 2 closure |

Converged (>=3 seats) and applied in plan v3: one provenance wording with proving keys (5/5); risk acceptance file before any automated filling, fallback no longer unsigned (4/5); B0b three-outcome verdict (3/5). Two seats: live-write definition + operator decision D1 (a standing-rule conflict, so taken); named builder/reviewer. Single seats, taken: B4 binding, readback_source, CSV-branch bar; Sprint 2 closure -> D3.
Rejected: none. Vote r2 follows on plan v3. Absent: none in r1.

## Round 2 (plan v3)
| seat | vote | requests |
|---|---|---|
| deepcode | REQUEST-CHANGES | B0b PASS must not rest on a live publish; B3 draft deletion bound to captured IDs |
| deepseek | APPROVE-AS-IS | D1-D3 need a mechanical freeze gate (note: seat saw only a code-map excerpt, not the docs) |
| gpt6-luna-max | APPROVE-AS-IS | none |
| gpt61-sol | APPROVE-AS-IS | none |
| opus | REQUEST-CHANGES | source class per field (amazon_page / rule_config) so unproven_fields=0 is reachable; click allowlist |
| codex | REQUEST-CHANGES | same provenance inconsistency as opus (Definitions vs B3 vs FAIL criterion); fixed in all three clauses |

All requests applied in plan v4 (freeze gate script added as P0). Vote r3 on the delta to deepcode, opus, codex, deepseek (deepseek re-reads the real docs).

## Round 3 (plan v4)
| seat | vote | requests |
|---|---|---|
| codex | APPROVE-AS-IS | none |
| opus | APPROVE-AS-IS | notes (taken): exact config keys, German button labels, UNKNOWN needs a time limit and no default |
| deepcode | REQUEST-CHANGES | pin D-line format + test; description field missing from table, required-empty = FAIL |
| deepseek | REQUEST-CHANGES | verbatim PASS rule + on-disk confirmation path; freeze check run by CI/test with seeded-violation test (seat voted on the delta only, retrieval stale) |
| gpt6-luna-max, gpt61-sol | approved v3 in r2; v4/v5 changes only tighten, re-asked in r4 |

All applied in plan v5. Vote r4 on v5 to all five.

## Rounds 4-6 (plans v5-v7)
| seat | r4 (v5) | r5/r6 | final |
|---|---|---|---|
| codex | APPROVE | - | APPROVE (on v5) |
| deepcode | APPROVE | - | APPROVE (on v5; note: D1/D3 tokens, taken in v6) |
| gpt6-luna-max | APPROVE | - | APPROVE (on v5) |
| gpt61-sol | APPROVE | - | APPROVE (on v5) |
| opus | REQUEST-CHANGES (quantity key location, required-empty clause) | r5 APPROVE on v6 | APPROVE (on v6) |
| deepseek | REQUEST-CHANGES (could not read files) | r5 REQUEST-CHANGES (D1 denied blocks B0b; two read-back sources); r6 APPROVE on v7 | APPROVE (on v7) |

Disclosure: v6/v7 changes only tighten (token pins, one extra check, two read-back sources, D1-denied blocks B0b); they were not re-sent to codex, deepcode, luna, sol.
Driver's vote (Claude): APPROVE-AS-IS on v7. Remaining before freeze: operator D1-D3 in `docs/sprint3-decisions.md`, `tools/sprint3_freeze_check.py` (P0), GitHub board cards, the operator's explicit freeze. Sprint 2 review: D3.
