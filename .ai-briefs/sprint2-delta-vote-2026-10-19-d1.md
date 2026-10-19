# Sprint 2 DELTA vote d1 (2026-10-19) - ai_dropshipping

You are a voting seat. Answer in <=120 words, plain text, no tool calls. The frozen package (plan docs/sprint2-plan.md, bar docs/sprint2-bar-v7.md, vote r7 unanimous 6/6) is changed ONLY by this delta, which the operator asked for ("pull T2 forward").

## What happened (measured 2026-10-19)
T0 could not finish: amazon.de resets the TLS handshake for the app's bundled Playwright Chromium (`dropship_desk/amazon/product.py:93`, `p.chromium.launch(headless=True)`) and for curl (ERR_CONNECTION_RESET). The installed Chrome (`channel="chrome"`, headless, fresh context, no login) fetched 30 of 45 ASINs; the rest reset. Without a working fetch no card of the sprint can run, including T0's price snapshot and the end-to-end feature.

## The delta
1. NEW card **S2-T2a - reliable Amazon.de fetch** (size S, builder codex, parent #20): `fetch_product_offer`/`fetch_variation_offers` launch the installed Chrome (`channel="chrome"`) with a fresh, logged-out context, with a bounded retry (max 3 attempts, 5 s backoff) and a clear error (`AMAZON_UNREACHABLE`) when all fail. Done: unit tests with a stubbed launcher (retry count, error), and one real fetch of 3 known ASINs recorded in the card (no cart, no purchase, no login). It does not touch the bar, the fixture or the controls.
2. Order: T2a goes FIRST, ahead of T0's snapshot step; T1 and T2 follow as planned. The bar v7 is unchanged. The bar's INCONCLUSIVE rule for an unreachable Amazon is unchanged (a row ending `AMAZON_UNREACHABLE` is an ordinary E row that lowers p).

Strongest case against: it adds a card to a frozen sprint and a retry can hammer Amazon.

Questions: 1. `VOTE: APPROVE-AS-IS | REQUEST-CHANGES | REJECT` 2. at most 2 exact changes 3. one risk.
