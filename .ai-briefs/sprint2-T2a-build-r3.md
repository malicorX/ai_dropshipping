# S2-T2a build brief, round 3 (builder: deepcode). Same worktree/branch s2-t2a (rounds 1-2 committed). Heartbeat to `_heartbeat.txt`; report in `_report3.md`.

## Correction of the driver's round-2 diagnosis (driver was wrong)
The ~2 KB pages for `B0HCNC2L81` etc. are NOT block pages. Measured: title `Seite wurde nicht gefunden` (Amazon "page not found": the ASIN does not exist or was delisted). Round 2 made them retryable `blocked_page`, so six non-existent ASINs now burn 3 attempts each and are reported as AMAZON_UNREACHABLE. That is wrong and also feeds the consecutive-failure cap with non-network failures.

## Deliverable (only `dropship_desk/amazon/product.py` and `tests/test_amazon_fetch.py`)
1. A page whose `<title>` contains `Seite wurde nicht gefunden` or `Page Not Found` (case-insensitive), or the `/dp/` page of a non-existent ASIN, is a TERMINAL, NON-RETRYABLE failure: raise `AsinNotFound(RuntimeError)` with message starting `ASIN_NOT_FOUND: <asin>`; 1 attempt, no sleep. It does NOT increment `_consecutive_failures` (it is not a network failure) and does not reset it either.
2. A short page (< 20,000 chars, no `id="productTitle"`) that is NOT a not-found page remains the retryable `blocked_page` (keep the round-2 behaviour for that case).
3. Tests: not-found page -> AsinNotFound, 1 attempt, no sleep, counter unchanged after 25 consecutive not-found ASINs (the 26th call still launches); short unknown page -> still retried 3x -> AmazonUnreachable blocked_page; the round-2 tests that used a not-found-like page as 'blocked' must be updated to a genuinely unknown short page.
4. RED first (paste), GREEN full suite, mutants that must FAIL the suite: not-found treated as retryable; not-found increments the counter; cap 2000; MIN_GAP 0; channel removed.
No real Amazon request in tests. Do not touch other files.
