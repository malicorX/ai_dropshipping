# Sprint 3 bar v1: field sources and read-back comparisons

Pinned against the code in this worktree and `docs/sprint3-plan.md` v13.
This is a provenance contract for the browser implementation, not evidence that
the current API implementation or any particular item passes the bar. No browser
read-back comparator is implemented by P0.

## Evidence inspected and limits

Inspected `dropship_desk/models.py`, `dropship_desk/ebay/listing.py`,
`dropship_desk/ebay/aspects.py`, `dropship_desk/ebay/taxonomy.py`, and the draft,
media, price and account-cache writers cited below. `data/` is ignored by Git
and was absent from this worktree at inspection. Consequently:

- **MISSING: `data/ebay_production.json`**, the file named in the plan. No keys or
  policy ID values from that file can be verified here. The actual account-cache
  writer uses `data/ebay_account_production.json`, which is also absent.
- **MISSING: an actual `data/products/<ASIN>/listing_draft.json`**, including
  `data/products/B0D87HWM4W/listing_draft.json`. The exact draft keys below come
  from the writer and its callers, not from an invented sample artifact.
- **MISSING: the item's persisted Amazon evidence, media files, category
  selection, price and policy values.** Code defines their paths and keys;
  it does not establish the values for B0D87HWM4W.

Paths under `data/` below are the default paths: `config.DATA_DIR` is derived
from `DROPSHIP_DATA_DIR` or `<runtime root>/data`. The draft writer is
`product_media.save_draft_artifacts`; it writes
`data/products/<ASIN>/listing_draft.json`. Database candidate dictionaries come
from `db.get_candidate_by_asin` / `db._row_to_dict`: `offer` decodes
`candidates.offer_json`, `listing_draft` decodes `candidates.listing_draft_json`,
and `ebay_price` is a candidate column in `data/dropship.sqlite3`.

## Per-field source-class table

Every filled field must have its listed source key and evidence. A required
field left empty fails. `MISSING:` identifies a gap to resolve before that field
can pass; it does not define a new key. Optional unproven product facts stay
empty / "Keine Angabe" as the plan specifies; a placeholder is not proof of a
required fact.

The comparison rules below are requirements for independent read-back after a
fresh reload of the review page and Drafts row. Both sources must be recorded
for each item. Match them to the captured draft ID, not its title or row
position. A value that a source does not expose is not an observed match;
every field needs independent eBay evidence, not an echo of the form inputs.

| Field | Source class | Exact existing key, file and function; evidence gaps | Read-back comparison rule |
|---|---|---|---|
| Title | `amazon_page` | Draft JSON `title`; candidate `listing_draft.title`; Amazon source `offer.title` (`models.OfferIn.title`). `ollama_client.generate_listing_draft(amazon_title=...)` also writes draft `source_amazon_title` and `source_asin`. `listing._stage_unpublished` prepares the sent title using `listing._clip(..., 80)` and sends `product.title`. `draft_title` and `amazon_title` in `taxonomy.verified_listing_specifics` are function parameters, not persisted JSON keys. **MISSING: persisted keys literally named `draft_title` or `amazon_title`; use the existing paths above.** | Compare the independently observed title with the frozen, prepared draft `title` after the same whitespace collapse and 80-character clipping as `_clip`. Preserve case, punctuation and variant/size/color wording; no fuzzy match. Separately require the Amazon title/facts supporting every product claim. |
| Description | `amazon_page` | Draft JSON / candidate `listing_draft.description_html` and `bullet_points`; input facts `offer.title`, `offer.bullets`, `offer.specs` (`OfferIn`). `ollama_client.generate_listing_draft` calls `enforce_facts` then `listing_template.apply_listing_template`; its structured inputs include `intro_html`, `advantages`, `functions`, `scope_of_delivery`. `listing._stage_unpublished` applies `ebay_safe_description` and sends `offer_payload.listingDescription`; the shorter `product.description` is produced by `_inventory_description` and is not the full listing description. **MISSING: persisted per-claim links back to Amazon facts.** The template also adds `ListingShopSettings` shop copy; that copy is not Amazon evidence. | Compare the independently rendered listing description to the frozen `ebay_safe_description` output, retaining ordered paragraphs, lists, product facts and link targets. Decode HTML entities and normalize presentation whitespace only; do not compare the shorter inventory description or accept omitted/added claims. Verify product claims against Amazon bullets/specs separately. Any shop-template claim without an explicitly approved source entry fails this `amazon_page` row; template defaults alone do not satisfy it. |
| Item specifics | `amazon_page` | `aspects.resolve_aspects(aspect_defs, offer, overrides, ...)` returns `(filled, problems)` from `offer.title`, `offer.bullets`, `offer.specs`. `taxonomy.verified_listing_specifics` returns `aspects`, `brand`, `mpn`, consumed as inventory `product.aspects`, `product.brand`, `product.mpn`. Manual values can enter through `data/products/<ASIN>/ebay_overrides.json` key `aspects`. The resolver supplies default brand/MPN values and taxonomy passes `fill_placeholders=True`. **MISSING: persisted per-aspect Amazon evidence mapping; an override or default alone is not `amazon_page` proof.** | Compare the complete observed aspect-name-to-value-list mapping with the frozen verified mapping; normalize whitespace only, treat value lists as unordered collections while retaining multiplicity, and fail on missing, added or different values. Require the corresponding Amazon title/bullet/spec evidence for each filled product fact, including brand and MPN. Required unknowns and unsupported defaults cannot pass merely because the resolver returned them. |
| Condition | `amazon_page` | `listing._stage_unpublished` sends the literal inventory key `condition: "NEW"`. `models.OfferIn` has no `condition` field, and the inspected draft writer/generator does not create one. **MISSING: Amazon-backed condition source key/value and a pinned browser form condition mapping.** | Read the selected condition independently and compare its pinned identity to an evidenced source condition. The current literal `NEW` is a code default, not Amazon proof; matching it alone fails. Until source evidence and the form mapping exist, condition is unproven and a required condition blocks the item. |
| Photos | `amazon_page` | `OfferIn.image_urls`, `OfferIn.local_images`; draft `media.source_urls`, `media.local_images[]` entries `index`, `source_url`, `path`, `api_path`, written by `product_media.save_draft_artifacts`. `download_product_images` writes `data/products/<ASIN>/media.json` with `source_urls`, `local_images`, `ok_count`, `fail_count`; files are in `images/`. `pictures.prepare_image(path)` returns `(name, bytes)` for a re-encoded JPEG; `collect_image_urls` returns URLs sent as `product.imageUrls`; listing state stores `image_count`. **MISSING: a draft key `images`, persisted hashes of the re-encoded bytes, and a durable binding from those bytes to observed eBay images.** The SHA-1 fragment in the generated filename hashes the original bytes, not the re-encoded JPEG. | Require the exact selected count, order and image identities after reload, each traced to its Amazon source and its frozen re-encoded file hash. Verify uploaded file bytes against that hash and independently bind the observed eBay image to the upload. URLs, filenames, thumbnail counts or original-file hashes alone do not establish the required match. If eBay transforms the image, byte equality with a downloaded thumbnail is not proof; without a verified identity binding the field fails. |
| Category | `rule_config` | `aspects.load_overrides` reads `data/products/<ASIN>/ebay_overrides.json` key `category_id` (optional `category_name`); otherwise `taxonomy.verified_listing_specifics` returns `category_id`, `category_name`, `category_path`, `tree_id`. Its fallback uses `aspects.category_fits` on eBay suggestions and may use `ollama_client.pick_category`. `listing._stage_unpublished` sends `offer_payload.categoryId` and `save_listing_state` records `category_id`, `category_name`, `category_path` in `data/products/<ASIN>/ebay_production.json`. **MISSING: this item's recorded override or verified selection result.** | Compare the observed category ID exactly as a string against the frozen selected `category_id`. A translated display name or a plausible category is insufficient. Require the recorded override or verified selection result and corroborate its displayed path/name; never select a replacement during read-back. |
| Price | `rule_config` | Candidate `ebay_price`, `models.EvaluateRequest.ebay_price` / `EvaluateResponse.ebay_price`; `evaluate_service.run_evaluate` uses `margin.suggest_ebay_price` and `margin.evaluate_margin`. `MarginSettings` is defined in `models.py` (not `margin.py`); `db.get_margin_settings` reads settings key `margin`. Relevant keys are `ebay_fee_pct`, `ebay_fee_fixed`, `buffer_eur`, `min_margin_eur`, `min_margin_pct`. `listing.canonical_price` rounds via Decimal, `ROUND_HALF_UP`, to cents; `_stage_unpublished` checks `expected_price` against stored price when supplied and sends `pricingSummary.price.value` / `.currency` (`EUR`). Listing state stores `price`. **MISSING: this item's stored price and recorded settings; no price key is guaranteed in the draft JSON.** | Parse the observed German-formatted amount to decimal EUR and require exact cents equality to the frozen canonical `ebay_price`, plus currency `EUR`. No floating-point tolerance, rounding to whole euros or comparison to Amazon cost. Require the recorded margin inputs/settings supporting that price. |
| Quantity | `rule_config` | `dropship_desk/ebay/listing.py` constant `DEFAULT_QUANTITY = 5`; `_stage_unpublished` sends `availability.shipToLocationAvailability.quantity` and `offer_payload.availableQuantity`. `quantityLimitPerBuyer = 2` is a separate field, not the listing quantity. **MISSING: a persisted draft quantity key; the existing named source is the constant.** | Compare the independently observed available quantity as an exact integer with the frozen `DEFAULT_QUANTITY` value (currently 5). Do not confuse availability with the per-buyer limit or Amazon stock. Record the rule version used; a missing or non-integer observation fails. |
| EAN / GTIN | `amazon_page` | Existing payload fills `product.ean = [_candidate_ean(row) or "Nicht zutreffend"]` (`listing.py`); `_candidate_ean` reads only the exact keys `ean`, `EAN`, `gtin`, `GTIN` from the offer, the draft or the candidate row. **MISSING: an Amazon-page EAN source in the inspected offer model; the placeholder "Nicht zutreffend" is not proof from the Amazon page.** | Compare the displayed EAN/GTIN field independently with the source key when one exists; with no key the field stays empty / "Keine Angabe" and the placeholder counts as an unproven filled value. |
| Policies | `rule_config` | `account_setup.account_cache_path("production")` names `data/ebay_account_production.json`; `ensure_seller_setup` returns and saves `fulfillment_policy_id`, `payment_policy_id`, `return_policy_id` (and `merchant_location_key`). `_stage_unpublished` maps those IDs to `listingPolicies.fulfillmentPolicyId`, `.paymentPolicyId`, `.returnPolicyId`. **MISSING: `data/ebay_production.json` named by the plan, the actual account-cache file, and their production policy values in this worktree.** The per-product `data/products/<ASIN>/ebay_production.json` is listing state, not the account policy cache. | Require exact identity equality for all three frozen production policy IDs on independent read-back. Labels alone are insufficient unless independently mapped to the same IDs for the target account. A missing policy, an ID from another account/environment, or an unverified label-to-ID mapping fails. |

Other filled form fields are not implicitly covered by these rows. For example,
the existing API payload also contains tax, merchant location, listing duration
and a per-buyer limit; this table does not silently authorize their browser
counterparts. The plan's rule still applies: a filled field absent from the
table, or a required field left empty, fails. Resolving the documented gaps is
future implementation/evidence work, not permission to change live code in P0.

The following complete Registered bar section is copied byte-for-byte from
`docs/sprint3-plan.md`, including the two record kinds and common failure rules.

## Registered bar (robot branch)
Two separate record kinds in `data/browser_runs.jsonl`:
- `kind = live_probe` (D4, exactly one line, only B0D87HWM4W): fill, read-back 0 mismatches / 0 unproven fields, then ONE operator-typed `LIVE 1` submit; the typed confirmation carries the verified payload hash in B4's single canonical schema (env, seller id, target account, eBay draft ID, all verified fields/images/policies; on-disk arm/UNKNOWN record, no in-memory nonces); the pre-click audit records the gate names from `config.live_write_gate_missing()` and the hash, and a closed gate aborts (test). The D4 draft is retained for the submit (not deleted by B3 cleanup). The submit is logged in `live_audit.jsonl` and is not counted in the draft bar.
- `kind = draft_bar`: >= 10 real drafts in a no-submit run; `readback_mismatch = 0`; `unproven_fields = 0`; `submit_clicks = 0`; `foreground_events_ours = 0`; one screenshot per item; `readback_sources = review_page,drafts_row` (both required per line); drafts deleted afterwards.
**FAIL even if every task is done:** a filled value without its listed key in the per-field source-class table (Definitions), or a required field left empty; any submit click during measurement; a read-back that only echoes typed values; the robot triggers an account restriction.
It proves filling and persistence, not publishability and not source truth. The first live submit is a separate operator decision and is the first real use (Rule 10).

