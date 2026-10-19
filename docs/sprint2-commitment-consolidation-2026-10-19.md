# Sprint 2 commitment vote consolidation (2026-10-19)

| round | seat | vote | requested changes |
|---|---|---|---|
| r1 | codex | REQUEST-CHANGES | split commitment/source freeze; zero-request exemption for C5; non-vacuous run C |
| r1 | deepcode | REQUEST-CHANGES | measurement freeze + SHA pin (blocker); executable census + SKU->ASIN; exact expectations + price snapshot |
| r1 | opus | REQUEST-CHANGES | baseline census before freeze; SKU->ASIN rule; register control ASIN IDs |
| r1 | deepseek | NO VOTE | returned tool-call text only (re-dispatch) |
| r1 | gpt61-sol | REQUEST-CHANGES | same three as codex |
| r1 | gpt6-luna-max | REQUEST-CHANGES | run C executable via clean sandbox; C6 fail-closed; sandbox-only claim |

All requested changes converge and none conflict; all applied in bar v2 (see plan 'Plan changes'). 

| r2 | codex | REQUEST-CHANGES | price-flip verdict precedence with worked cases |
| r2 | deepcode | REQUEST-CHANGES | run C contradiction (blocker); per-run deadline; price-snapshot method |
| r2 | opus | REQUEST-CHANGES | define run C reset; p after run A; where C6 is injected |
| r2 | deepseek | REQUEST-CHANGES | census-anchored classification; deterministic run C kill; C5 hard network deny |
| r2 | gpt61-sol | APPROVE-AS-IS | none |
| r2 | gpt6-luna-max | APPROVE-AS-IS | none |

r2 changes all applied in bar v3 (docs/sprint2-bar-v3.md). No conflict between seats. 

| r3 | codex | APPROVE-AS-IS | none |
| r3 | deepcode | APPROVE-AS-IS | 3 non-blocking T0 clarifications (applied) |
| r3 | opus | APPROVE-AS-IS | 3 non-blocking clarifications (applied) |
| r3 | deepseek | REQUEST-CHANGES | freeze C-set artifacts; C1 vs ERROR_RETRYABLE; C5 both refusal subcases |
| r3 | gpt61-sol | APPROVE-AS-IS | none |
| r3 | gpt6-luna-max | APPROVE-AS-IS | none |

All applied in bar v4. 

| r4 | codex | APPROVE-AS-IS | none |
| r4 | deepcode | APPROVE-AS-IS | 3 non-blocking (applied) |
| r4 | opus | REQUEST-CHANGES | run B expectation conditional on run A; run C wording offerId+listingId |
| r4 | deepseek | APPROVE-AS-IS | 3 non-blocking (applied) |
| r4 | gpt61-sol | APPROVE-AS-IS | none |
| r4 | gpt6-luna-max | APPROVE-AS-IS | none |

Applied in bar v5. 

| r5 | codex | APPROVE-AS-IS | none |
| r5 | deepcode | REQUEST-CHANGES | C1 exactly one offer per ASIN across A and B; inline price-flip exemption in rule 1 |
| r5 | opus | APPROVE-AS-IS | 2 optional clarifications (applied) |
| r5 | deepseek | APPROVE-AS-IS | none |
| r5 | gpt61-sol | APPROVE-AS-IS | none |
| r5 | gpt6-luna-max | APPROVE-AS-IS | none |

Applied in bar v6. Next: r6 to all six.
