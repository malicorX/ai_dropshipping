# GOAL (DRAFT - proposed 2026-11-10, not yet confirmed by the operator)

**Goal:** Amazon.de links become correct, live eBay.de listings, automatically and in volume.

**Bar:** every live item has only facts proven from the Amazon page (nothing invented; uncertain values empty or
"Keine Angabe"), a category that fits, own re-encoded images (never Amazon links), rewritten fact-based text.
First live item by the operator; then many items per run without hand-holding.

**Goal paths:** `dropship_desk/ebay/` (API + browser listing), `dropship_desk/amazon/`, `dropship_desk/margin.py`,
`dropship_desk/models.py` (drafts), `upload_items/`, the UI button flow.

**Off-goal examples:** ads/Promoted Listings, new marketplaces, UI polish, Amazon purchasing (forbidden), extra reports.

Current blocker (2026-11): eBay blocks API listing for account butterflypro (errorId 25019, ref 1234519).
Sprint 3 goes around it through the web listing form.
