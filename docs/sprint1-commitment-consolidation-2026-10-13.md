<!-- disposition: decision-doc -->
# Sprint 1 commitment vote consolidation - 2026-10-13

Seats voting: codex, deepcode, deepseek, gpt6-luna-max, gpt61-sol, nv-nemotron, opus (opus absent in r1: no_quota). nv-glm failed in planning and did not vote.

| round | APPROVE-AS-IS | REQUEST-CHANGES | what moved |
|---|---|---|---|
| r1 | 0 | 6 (opus absent) | undefined cut line, bar holes, identity, T1 vs freeze |
| r2 | deepcode, nv-nemotron | codex, deepseek, luna, sol, opus | per-ASIN-across-SKUs, rule 4/5 collision, INCONCLUSIVE cases |
| r3 | 0 | 6 | violations fell through to rule 5; controls C1/C2; T1 before freeze accepted by all 6 |
| r4 | codex, deepseek, nemotron | deepcode, luna, sol, opus | NOT_MET outranks INCONCLUSIVE; retryable exception scope |
| r5 | codex, sol | 5 | 2a applies to all rows; "executed" defined |
| r6 | 5 | deepcode, opus | zero-request scenarios; M6/M7; distinct row ids |
| r7 | **7 of 7** | 0 | opus optional: define request as any HTTP call |

Rejected along the way: moving M4/M5 to Sprint 2 (deepseek, r2); a cosine threshold and failure-mode matrix (nv-nemotron, r1); mandatory rows checked by 2d only (nv-nemotron, r5).
Disclosure: after the unanimous r7, I reordered one misplaced sentence in rule 2a and added opus's optional "request = any HTTP call" definition. Recorded in the plan changes. Whether that needs a confirming round is the operator's call.
Driver's own vote: APPROVE, conditional on T1 landing before the freeze comment and the operator's explicit go. Residual risk named by the seats: five mandatory remote scenarios plus |E| >= 15 in one week; a sandbox pass does not show production behaviour.
Not yet done: T1 (24 uncommitted files, awaiting the operator's go), operator freeze.
