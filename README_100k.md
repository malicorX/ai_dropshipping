# Roadmap: 100,000 products

This is not a feature list for Dropship Desk as it exists today. The current app is a **semi-auto desk**: search Amazon.de, keep a small Queue, write one listing, send unpublished, Publish by hand. That path cannot produce a 100k-SKU eBay shop, and pretending it can (faster clicks, more Playwright, more Ollama) will get the seller account banned or the Amazon session burned before it gets you a catalog.

**Read this as a business/architecture plan, not as “turn on auto-publish.”** Auto-publish stays off until a later phase that has a kill switch, inventory truth, and a human still owning VeRO / policy.

---

## 1. First correction: 100k of *what*?

Three numbers get mixed up. They must stay separate.

| Number | Meaning | What actually constrains it |
|--------|---------|-----------------------------|
| **Catalog** | ASINs you *could* list (DB rows with price, images, category, copy) | Amazon data rights, storage, matching, uniqueness |
| **Live eBay SKUs** | Offers buyers can buy *right now* | eBay seller limits, insertion fees, search dilution, oversell risk |
| **Serviceable SKUs** | Live items you can fulfill the same day if they sell | Order desk, Amazon buy reliability, cash, returns |

**The useful target is not “100k live listings.”** It is “a large catalog, a much smaller live slice that is in stock at a passing margin, and an order pipeline that does not drown you.”

A shop with 100k published items and 8 orders/day is worse than 2,000 live items that actually sell. eBay search also punishes thin, duplicate, out-of-stock catalogs. New and early sellers on eBay.de often cannot list 100k even if the API would accept the calls; limits rise with sales, defects, and Store subscription — they are not a Dropship Desk setting.

**Recommended north star**

- Catalog: 50k–100k *child* ASINs (sizes/colors already exploded).
- Live: start at **hundreds**, then **low thousands**, only what passed a fresh stock/price check in the last N hours.
- Never keep a live offer whose Amazon buy would fail the margin rules *today*.

If you still want a vanity “100k live” later, that is a Store + limit-raise + ops problem, not a UI problem.

---

## 2. Why the current workflow dies before 1,000

What the app does now (Find → Queue → List on eBay → unpublished → Publish):

- One Playwright browser against amazon.de, with multi-second pauses and CAPTCHA stops.
- One local SQLite file, one product folder, one LLM draft, one Inventory SKU `DD-{ASIN}`.
- Copy is generated per ASIN on a local Ollama box.
- Publish is a second click on purpose.
- Amazon seller/country filters exist in Settings but the scrape does not fill those fields.
- There is no Order desk: a sale still means a human buys on Amazon and ships to the eBay buyer.
- Quantity on the eBay offer is a stub (`5`), not Amazon stock.

Rough time if you stayed on this path (optimistic, no CAPTCHA, no policy hits):

| Step | Per SKU | 100,000 SKUs |
|------|---------|----------------|
| Amazon PDP + images | tens of seconds | months of wall clock on one PC |
| LLM unique copy | tens of seconds | months, and quality collapses |
| eBay Inventory create + offer + publish | several API calls | weeks of rate-limit, plus insertion fees |
| Human review | even 20 seconds | ~23 days of nonstop clicking |

The bottleneck is not the tab names. The bottleneck is **data ingest, listing uniqueness, live inventory truth, and fulfillment**. Those do not exist yet.

---

## 3. New problems that do not show up at 1–20 listings

These appear as soon as you leave “I looked at this item.”

### 3.1 Amazon data

Scraping amazon.de at catalog scale is the wrong ingest. It is slow, brittle, CAPTCHA-prone, and against Amazon’s conditions. At 100k SKUs you need a **licensed catalog feed** (Amazon Product Advertising API / official partner data), plus a *sparse* live price/stock probe only for SKUs you are about to list or that just sold.

Do not “solve” this by rotating residential proxies or farm accounts. That is a ban/legal path, not a product path.

### 3.2 eBay account physics

- **Quantity limits** on how many items you may have listed.
- **Insertion / Store** fees: 100k live SKUs is a monthly bill, not a one-time API job.
- **Sell API rate limits** and Inventory bulk vs one-offer-at-a-time (today: one ASIN).
- **Duplicate listings**: 40 kg and 20 kg as two items is correct; 40 kg listed ten times is a defect.
- **Search dilution**: 100k near-identical “Hantelset” titles with swapped adjectives look like spam.
- **Seller performance**: late dispatch, INR, returns, “item not as described” scale linearly with thin listings.
- **VeRO / brand**: a bulk catalog will ingest Nike, Bosch, licensed toys. One-by-one you notice; a pipeline will not unless you block brands.

### 3.3 Listing identity (this is where 100k shops die)

eBay and Amazon both care that you are not a 1:1 clone shop.

Today: one LLM pass per ASIN, Amazon images downloaded locally, shop HTML template appended. That is acceptable for dozens. At 100k:

- LLM-per-SKU is too slow and too random (wrong size in the title, invented specs).
- Template-only is fast and gets you policy/duplicate trouble if titles/descriptions are mechanical.
- Amazon image reuse at volume is a copyright/VeRO risk even if you “rewrote the text.”

You need a **hybrid**: structured facts from Amazon (title tokens, variation, bullets, identifiers) → deterministic German title/aspects → *small* unique layer (shop boilerplate you already have, plus a short generated intro **only if** facts are locked). Facts must win over the model. The current “model must mention 20 kg” guard is a preview of that rule, not a 100k system.

### 3.4 Variations

Amazon parents vs children is already a footgun at 20 items. At 100k it is the catalog.

- Store **one eBay listing per sellable child ASIN**, or **one eBay variation listing per family** (better UX, harder API). Today we flatten to children. Bulk should pick one model and stick to it.
- Never publish the Amazon parent hub.
- SKU must remain `DD-{child ASIN}` (or a successor that still maps 1:1 to a buy URL).

### 3.5 Inventory lie

A published offer with quantity 5 and a 12-hour-old Amazon price is a promise you did not check. At 20 SKUs you remember. At 5,000 you oversell.

You need a **sync loop**:

1. Probe Amazon (PA-API or paced PDP) for live SKUs on a schedule.
2. If OOS, price exploded, or delivery > max days → **end the offer** (not “leave it up”).
3. If still good → patch price/quantity.
4. Re-list from catalog when it recovers.

Without this, 100k live is 100k ways to get defects.

### 3.6 Orders (the real 100k problem)

If 0.05% of 20,000 live SKUs sell on a busy day, that is **10 Amazon purchases/day**. If 0.2% of 50,000 sell, that is **100/day**. Click-buy on amazon.de does not survive that.

Order desk is not a tab with a placeholder. It is:

- eBay order webhook / poll (`EBAY_ALLOW_TRACKING` is the existing gate).
- Map listing SKU → ASIN → current Amazon offer.
- Recheck price vs `max_amazon_buy` / margin **before** purchase.
- Place Amazon order to the **buyer’s shipping address** (or a legal 3PL flow — see risks).
- Write tracking back to eBay within the handling time you advertised.
- Exception queue: CAPTCHA, address rejected, Amazon cancelled, price jump, dangerous goods.

Until that loop is boring, **do not grow live SKUs**.

### 3.7 Money and ops that the margin formula ignores

- Returns: you paid Amazon, buyer returns to *you*, Amazon may not take it back.
- GPSR / product safety (EU): responsible person, warnings, for many categories you cannot legally dropship blind.
- Batteries, toys, cosmetics, food-contact, PPE: bulk ingest will include them.
- Packaging / Impressum / Widerrufsbelehrung: already in the listing template; at volume, one wrong handling-time is a defect rate.
- Chargebacks and “Artikel nicht angekommen” when CN sellers lie about delivery days.
- Cash: you buy after sale, but Amazon charges immediately; eBay pays later.

`buffer_eur` is a rounding fudge. It is not a returns reserve.

### 3.8 Policy / legal (high level, not advice)

Dropshipping on eBay.de is allowed only if you **are** the seller: you honor eBay buyer protection, dispatch times, and returns. Sourcing from Amazon does not make Amazon the seller. Amazon’s conditions generally forbid using their site as a systematic warehouse for resale automation. Scaling is where that conflict stops being theoretical.

This repo should stay on **your** machine, **your** seller account, with kill switches. Multi-accounting, CAPTCHA farms, and fake invoices are out of scope on purpose.

---

## 4. Phased plan

Do not skip phases because “we already listed in sandbox.”

### Phase 0 — Prove the unit (now → ~50–200 live)

Stay on the current desk.

- Only child ASINs, never parents.
- Publish only after reading the title (size/color must be in it).
- Measure: time-to-first-sale, Amazon buy success, actual margin vs formula, return rate, defects.
- Build a **paper Order desk**: when an eBay sale happens, a checklist (recheck Amazon → buy → tracking). No auto-buy.

**Exit:** a handful of real live sales without a defect. If this fails, 100k will fail louder.

### Phase 1 — Catalog, not listings (0 → 10k rows in DB)

Replace “Find 20 hits” with a **catalog builder**:

- Seed from keyword batches, category crawls via **PA-API** (or a bought feed), not 24/7 Playwright.
- Explode variations at ingest; persist children only.
- Store: ASIN, parent, label, price, stars, images (or image URLs + license note), identifiers (EAN/GTIN if present), category guess, reject reasons.
- Hard filters as data, not UI folklore: brands blocklist, GPSR-ish categories blocklist, min stars/reviews, max delivery, margin at suggested eBay price.
- SQLite will get uncomfortable; plan Postgres (or SQLite + object store for images) before 10k image folders on disk.

**Exit:** 10k *qualified* child ASINs with a refresh timestamp. Almost none of them live.

### Phase 2 — Listing compiler (no LLM in the hot path)

Build a deterministic **listing compiler**:

- Title: Amazon tokens + required variation + shop style, ≤80 chars.
- Aspects: BrandMPN fallback you already send; GTIN when you have it.
- Description: shop template + fact bullets (scope of delivery, size) + short unique intro.
- Images: prefer your own photos for winners; for long tail, a strict subset of Amazon images with a visible “Bild ähnlich / Herstellerbild” disclaimer is still a risk — treat branded goods as unlistable without rights.
- LLM: optional polish on a **sample**, or only for top-N by expected margin — never 100k blocking calls.

**Exit:** compile 1,000 listings to unpublished Inventory offers in sandbox without a human per SKU. Spot-check 50.

### Phase 3 — Bulk unpublished + sampled live (hundreds live)

- Inventory API bulk / batched `bulkCreateOffer` (today is single-SKU).
- Queue: “compiled → unpublished → eligible to publish.”
- Publisher: only SKUs that passed a **fresh** Amazon probe in the last hour.
- Daily cap (e.g. 20–50 new live/day) while eBay limits and defects are unknown.
- Keep Publish as a **batch confirm** (“publish these 40”), not a hidden auto-publish. `EBAY_AUTO_PUBLISH` stays false until Phase 5.

**Exit:** 200–500 live SKUs, sync job ending OOS offers, no VeRO strike.

### Phase 4 — Order machine (this unlocks thousands live)

- Poll/subscribe eBay orders.
- Recheck Amazon; if fail → cancel/relocate per your policy (prefer cancel over sending the wrong variant).
- Semi-auto Amazon buy: human confirms the first N, then allow-list automation (`AMAZON_ALLOW_PURCHASE`) with a daily order cap.
- Tracking back to eBay.
- Returns mailbox / DACH returns address — not “buyer, please return to Amazon.”

**Exit:** 20+ orders/week processed without you living in the Amazon cart. Then you may raise live count.

### Phase 5 — Scale live toward catalog (thousands → tens of thousands)

Only after Phase 4.

- Live set = top of catalog by (margin × expected demand × in-stock), refreshed daily.
- End the bottom 20% that never impress / never sell.
- eBay Store subscription, limit increases, insertion-fee math.
- Optional: eBay **variation listings** for families (one parent, many SKUs) to look like a real shop instead of 80 near-duplicate items.
- Monitoring: API errors, CAPTCHA, defect rate, INR, A-to-Z, Amazon cancel rate, cash lag.

**100k live** is an optional last step if (a) eBay grants the limit, (b) sync keeps OOS rate tiny, (c) orders are still serviceable. Many shops should stop at **5k–20k live** on a 100k catalog.

---

## 5. Architecture Dropship Desk would need

Keep the desktop app as the **cockpit**. Move the factory off the click-path.

```
Catalog ingest (PA-API / feeds)
        → Candidate DB (child ASINs, facts, reject reasons)
        → Compiler (title, aspects, HTML, images)
        → eBay Inventory (unpublished)
        → Publisher (only if live probe PASS)
        → Sync loop (price/qty/end)
        → Order worker (eBay order → Amazon buy → tracking)
        → Cockpit UI (exceptions, VeRO, caps, sandbox/live)
```

Concrete changes vs today:

| Today | At scale |
|-------|----------|
| Find job, hit_target 20 | Batch ingest, no human hit target |
| Queue table | Catalog facets: live / unpublished / blocked / stale |
| List on eBay + Ollama | Compiler + sample LLM |
| SQLite + `data/products/{ASIN}` | DB + object storage; don’t keep 100k HTML files as source of truth |
| One Inventory offer call | Bulk + backoff + idempotent SKU |
| Quantity = 5 | Quantity 1 (or real stock) + end-on-OOS |
| No orders | Order worker + exception inbox |
| Settings checkboxes unused | Real `sold_by_amazon` / seller country from PA-API |

Safety flags (`EBAY_ALLOW_LIST`, `AMAZON_ALLOW_PURCHASE`, no auto-publish) stay. Add:

- Max live SKUs
- Max publishes / hour
- Max Amazon purchases / day
- Brand and category denylists
- “End all live offers” panic button

---

## 6. What not to do

- Do not auto-publish 100k from the current Generate button.
- Do not scrape Amazon faster until it “works.”
- Do not list brands you cannot defend in VeRO.
- Do not use quantity 5 as a substitute for stock checks.
- Do not grow live SKUs faster than you can buy and ship.
- Do not treat sandbox success as live capacity.
- Do not run two eBay accounts to dodge limits.

---

## 7. Suggested timeline (calendar, not promises)

Assuming one person + this codebase, after Phase 0 sales exist:

| When | Output |
|------|--------|
| 2–4 weeks | Paper order checklist, brand denylist, variation discipline on every live item |
| 1–2 months | PA-API (or equivalent) ingest, 10k catalog rows, compiler MVP |
| +1 month | Bulk unpublished in sandbox, 200 live on production with sync-end |
| +1–2 months | Order worker, daily purchase cap, 500–2,000 live |
| Later | Live set sized to orders you can run; catalog toward 100k |

If Phase 0 never produces clean sales, stop. A bigger catalog will not fix a bad unit.

---

## 8. Immediate next build (when we leave this document)

Smallest slices that actually point at 100k, in order:

1. **Order desk v0** — list eBay orders, show ASIN + “recheck Amazon” + checklist. No purchase automation.
2. **End-offer / relist** — when Amazon is OOS or margin fails, end the live offer.
3. **Brand/category denylist** — before any bulk compiler.
4. **PA-API (or paid feed) spike** — prove we can fill `sold_by_amazon`, GTIN, and price without Playwright as the backbone.
5. **Listing compiler** — generate title+HTML from facts; LLM optional.

Until (1) and (2) exist, “100k products” is a catalog fantasy sitting on top of a gift-shop workflow.

---

*This file is a plan. It does not enable auto-publish or Amazon purchase. Those remain explicit `.env` gates.*
