# S2-T2a build brief: reliable Amazon.de fetch (builder: deepcode). Card #31, spec docs/sprint2-delta-d1.md (read it first).

Working dir: this worktree (branch s2-t2a). You may edit files; you cannot commit or push (the driver does). Budget: one packet, finish within ~25 minutes. Write a one-line `PARTIAL: <what is done>` heartbeat to `_heartbeat.txt` in the worktree root about once a minute (delete nothing else).

## Deliverable
Change `dropship_desk/amazon/product.py` (only that file plus a new test file `tests/test_amazon_fetch.py`):
1. `_load_pdp` launches the installed Chrome: `p.chromium.launch(channel="chrome", headless=True)` with a fresh logged-out context (as now, `browser.new_context(...)`, no storage state, no user-data-dir). Factor the launch/goto into a small function so a test can stub it (for example `_launch_browser(p)` and `_goto(page, url)`), without changing public function names.
2. Retry ONLY when the exception text contains `ERR_CONNECTION_RESET` or is a Playwright timeout: max 3 attempts, 5 s base backoff plus up to 1 s random jitter between attempts. Sleeping must go through `time.sleep` so the test can monkeypatch it. A captcha or parse failure is NOT retried (stop early).
3. Errors: after the last attempt raise `AmazonUnreachable(RuntimeError)` whose message starts with `AMAZON_UNREACHABLE` and names the ASIN, the attempt count and the error class of the last failure. If Chrome cannot be launched at all (Playwright error mentioning that the `chrome` channel/executable is missing), raise `ChromeNotFound(RuntimeError)` with message starting `CHROME_NOT_FOUND`; this is never reported as AMAZON_UNREACHABLE.
4. Pacing: a module-level `MIN_GAP_SEC = 5.0` between two consecutive ASIN loads in the same process (use a monotonic timestamp; sleep the remainder). A consecutive-terminal-failure counter `MAX_CONSECUTIVE_FAILURES = 20` (counts terminal ASIN failures, not retry attempts): when reached, further fetches raise `AmazonUnreachable("AMAZON_UNREACHABLE: failure cap reached ...")` immediately; any success resets the counter. Expose `reset_fetch_state()` for tests.
5. Keep every existing public name and signature working (`fetch_product_offer`, `fetch_variation_offers`, `_fetch_pdp_bundle`, `_load_pdp` return shape). The existing tests must still pass.

## Tests (tests/test_amazon_fetch.py, no network)
Stub the launcher/goto and `time.sleep`. Cases: success on first try (1 launch); reset then success (2 attempts, one sleep of 5-6 s); three resets -> AmazonUnreachable with attempt count 3; timeout retried; captcha NOT retried (1 attempt); ChromeNotFound is distinct from AmazonUnreachable; failure cap (20 failures, the 21st fails immediately without launching); success resets the counter; MIN_GAP enforced between two ASINs.

## Rules
- RED first: write the tests, run `python -m pytest -q tests/test_amazon_fetch.py` against the UNCHANGED product.py and paste the failure output into `_report.md`.
- Then implement; paste the GREEN output and the full-suite result (`python -m pytest -q`) into `_report.md`.
- Mutants: apply each of these to your finished code, show the suite fails, then revert: (a) retry on any exception, (b) remove the sleep between attempts, (c) channel="chrome" removed, (d) failure counter not reset on success. Record each in `_report.md`.
- No real Amazon request in tests. No eBay, no cart, no login. Do not touch other files.
