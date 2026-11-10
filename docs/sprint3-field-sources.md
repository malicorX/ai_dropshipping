# Sprint 3 field sources (resolves S3-FINDING #48)

Date 2026-11-10, driver decision under operator "1." (B0 path). Corrects the plan v13 table without touching the registered bar text; B1-B3 use these keys. Anything not listed is `amazon_page` or fails.

| field | class | source / key | rule |
|---|---|---|---|
| condition | rule_config | operator rule: Amazon-sold new goods -> "Neu" (API: `NEW`, `listing._stage_unpublished`) | not provable from the page; stated here once, shown in the read-back as rule_config |
| quantity | rule_config | test item: **1** (hard value for the B0D87HWM4W probe, not `DEFAULT_QUANTITY = 5`) | 5 would promise stock we do not hold; revisit before volume |
| policies (shipping/payment/return) | rule_config | `data/ebay_account_production.json` keys `fulfillment_policy_id`, `payment_policy_id`, `return_policy_id` (plan said `data/ebay_production.json`, wrong) | read-back compares the policy IDs eBay shows |
| location | rule_config | `merchant_location_key` in the same file | the old invented "Invalidenstrasse 1 Berlin" stays an open item, not used by the web form unless eBay requires it; then the operator decides |
| EAN | amazon_page or empty | real GTIN from the Amazon page, else the eBay value "Nicht zutreffend" / empty | placeholder is never proof of an EAN |
| category, price | rule_config | as in bar-v1 | unchanged |

Plan change: none to the frozen bar; this file is the source table B1-B3 must follow. If B0 shows the web form needs a field not listed, it stays empty or the item fails; no value is invented.
