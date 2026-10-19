# Sprint 2 delta d1 (2026-10-19): card S2-T2a, reliable Amazon.de fetch

**Card S2-T2a** (size S, builder codex, reviewer opus, tester deepcode, critic deepseek; parent task group #20), runs FIRST, before T0's snapshot step. Bar v7 is unchanged.

Definition: `fetch_product_offer` / `fetch_variation_offers` (`dropship_desk/amazon/product.py`) launch the installed Chrome (`channel="chrome"`) with a fresh, logged-out context (no cookies, no profile). Retry only on `ERR_CONNECTION_RESET` or a timeout, max 3 attempts, 5 s backoff with jitter, and at least 5 s between ASINs; fetches stay sequential; a per-run failure cap (default 10 consecutive failures stops the run). Errors: `AMAZON_UNREACHABLE` (all attempts failed, per-ASIN log with attempt count and error class) and `CHROME_NOT_FOUND` (the Chrome channel cannot launch; never logged as AMAZON_UNREACHABLE). A non-retryable failure (captcha, parse) stops early.

Done: unit tests with a stubbed launcher (retry count, early stop, both errors); the 15 ASINs that reset in T0's first snapshot are re-run through the new fetch and the success count is recorded in the card (three known-good ASINs alone are not enough); no cart, no purchase, no login, no eBay request.

A row ending `AMAZON_UNREACHABLE` is an ordinary E row that lowers p (bar rule 1 (i)). The fixture/bar/controls are untouched.
