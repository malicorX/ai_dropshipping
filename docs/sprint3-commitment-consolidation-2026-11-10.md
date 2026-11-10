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
| codex | no r2 answer recorded | absent |

All requests applied in plan v4 (freeze gate script added as P0). Vote r3 on the delta to deepcode, opus, codex, deepseek (deepseek re-reads the real docs).
