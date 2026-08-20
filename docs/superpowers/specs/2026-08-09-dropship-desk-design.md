# Dropship Desk — Design Spec

**Date:** 2026-08-09  
**Status:** Draft for user review  
**Project:** `ai_dropshipping`  
**Goal:** Make money with Amazon.de → eBay dropshipping via a thin, owned Windows desktop app — not by cloning EbayGlitch.

---

## 1. Problem and success criteria

### Problem

Manual Amazon→eBay arbitrage is slow and error-prone (margin math, listing copy, order fulfillment). Third-party tools (e.g. EbayGlitch) can find products but create SaaS lock-in and do not own our margin/ops loop. Mass-uploading thousands of listings before unit economics are proven is a fee and account-risk treadmill.

### Success (v1)

- Paste one Amazon.de URL/ASIN → clear **PASS/FAIL** on real net margin after fees and buffer.
- Generate a usable eBay listing draft (title/description) via local LLM on sparky2.
- On a sale, show a **fulfillment card** so the human can buy on Amazon with customer ship-to in a guided, confirm-gated way.
- Daily use is a **native Windows window** (no routine CLI).
- No accidental Amazon purchase or eBay write while automation masters are off.

### Non-goals (v1)

- Forking or shipping EbayGlitch / proprietary extension code.
- Mass Amazon search / 100k listing flood.
- Fully unattended Amazon checkout.
- Multi-tenant SaaS.

---

## 2. Business model (explicit)

**Fulfillment:** Customer buys on eBay → we buy the same item on Amazon with the **customer’s shipping address** → Amazon ships to the customer. We do not warehouse goods.

**We remain in the middle** for money, support, refunds, disputes, and platform risk. Packing slips, price changes, and returns can still hurt; thick margins and low volume while learning are required.

**Inspiration only:** `init/` (chat notes, screenshots, EbayGlitch Product finder). Filter *ideas* may inform our own fetcher; **no copy of their proprietary code** into the product.

---

## 3. Approach

**Chosen:** Decision → draft → confirm (Approach 2), delivered as a ControlAi-style Windows desktop app.

1. Ingest ASIN/URL  
2. Snapshot Amazon offer  
3. Margin engine → reject or approve  
4. LLM listing draft (sparky2 Ollama)  
5. Human publishes on eBay (API listing later)  
6. Order → fulfillment card → optional Amazon cart assist → **human confirms purchase**

Mass product finder is a later add-on once this loop prints money.

---

## 4. System architecture

```text
Dropship Desk (PyWebView window)
        │
        └─ FastAPI on 127.0.0.1:<port>
                ├─ Product ingest + offer snapshot (Playwright)
                ├─ Margin engine (pure, tested)
                ├─ Listing copy → Ollama on sparky2
                ├─ Candidates / drafts / orders (SQLite)
                ├─ Safety gate (.env masters + Armed + confirms)
                └─ Later: eBay OAuth, Amazon cart/purchase assist
```

### Components

| Piece | Role |
|--------|------|
| `launcher.py` | Start uvicorn, open PyWebView (ControlAi pattern) |
| FastAPI app | Local API for UI and automation |
| React + Vite UI | Evaluate, Drafts, Order desk, Settings |
| SQLite `data/` | Candidates, drafts, fulfillment cards, audit log |
| Playwright | Amazon page snapshot; later cart fill |
| Ollama client | sparky2 `agents-a1` / `agents-a1-nonthink` for copy |
| Safety module | Env masters, Armed window, caps, confirm tokens |

### Data flow (happy path)

1. User pastes Amazon.de URL → normalize ASIN.  
2. Fetcher snapshots price, shipping, stock/delivery, seller signals.  
3. Margin engine computes net profit; UI shows PASS/FAIL.  
4. On PASS (or override), LLM produces listing draft → user copies/publishes on eBay → marks `listed`.  
5. Sale → fulfillment card (manual create in v1) → recheck Amazon → checklist → user buys → paste tracking.  

---

## 5. Windows app shell

Mirror **ControlAi** (`M:\Data\Projects\ai_nvidiaTool`) packaging, not its feature set:

- PyWebView + FastAPI + React/Vite  
- Dev: `start.bat` / `launcher.py --dev` with Vite  
- Prod window loads `ui/dist`  
- Later: PyInstaller one-dir `.exe`  
- Single-user, localhost only  

Do not import the ControlAi codebase wholesale; reuse the **pattern** (launcher, port find, frozen `data/` next to exe).

---

## 6. Margin rules

### Configurable defaults (Settings)

| Knob | Default |
|------|---------|
| `ebay_fee_pct` | 0.15 |
| `ebay_fee_fixed` | €0.35 |
| `buffer_eur` | €3 |
| `min_margin_eur` | €5 |
| `min_margin_pct` | 0.50 of `amazon_total` |
| Max delivery (days) | 10 |
| Min stock (if detectable) | >10, else must be in stock |
| Skip “Verkauf durch Amazon” | on (toggle) |
| Reject DACH sellers (DE/AT/CH) | on (toggle) |

### Formulas

```text
ebay_fees    = ebay_price * ebay_fee_pct + ebay_fee_fixed
net_proceeds = ebay_price - ebay_fees
net_profit   = net_proceeds - amazon_total - buffer_eur
margin_pct   = net_profit / amazon_total

PASS iff:
  net_profit >= min_margin_eur
  AND margin_pct >= min_margin_pct
```

- `amazon_total` = item price + shipping to DE at snapshot time.  
- `max_amazon_buy` defaults to snapshot `amazon_total`; user may tighten. Stored on candidate and enforced at order time.  
- Suggested eBay price: solve upward from `amazon_total` until PASS; round to psychological endings (e.g. x,99).

### Hard rejects (before or with margin)

1. Unreliable price (CAPTCHA, parse failure, incomplete offer)  
2. Out of stock / below stock threshold  
3. Delivery slower than max days (when detectable)  
4. Optional: Amazon retail-only / DACH seller  

### Order-time recheck

Re-fetch Amazon total. If `new_total > max_amazon_buy` or recomputed net profit &lt; 0 → **DO NOT BUY**; recommend cancel/relist.

---

## 7. UI screens

### Evaluate

- Paste URL/ASIN → Analyze  
- Snapshot + margin breakdown + PASS/FAIL  
- Edit eBay list price and `max_amazon_buy`  
- Save candidate; Generate listing draft (PASS, or override with confirm)

### Drafts

- Statuses: `rejected` · `ready` · `drafted` · `listed`  
- Show/edit LLM title, description, bullets  
- Regenerate / Copy / Mark listed (optional eBay item id)  
- v1 publish is manual in the eBay browser UI  

### Order desk

- v1: manually create card (eBay order id, ship-to, sold price, ASIN/candidate)  
- Later: eBay API fills inbox  
- Card: Buy block, Ship-to + copy, checklist, after-order tracking fields, STOP state  
- **“I placed the Amazon order”** only if last recheck passed (or forced with typed reason → audit)

### Settings

- Margin/filter knobs  
- Ollama base URL + model  
- Health: API, Ollama, automation master flags (read-only reflection of `.env`)  
- Armed status / remaining time (when automation exists)

---

## 8. Account automation and safety

### Intent (option C)

Plan **Amazon session automation** (cart fill; purchase always human-confirm) and **eBay API** (orders/tracking, later list). Both behind hard `.env` masters so nothing write-capable runs by mistake.

### `.env` masters (required)

```env
AMAZON_AUTOMATION_ENABLED=false
EBAY_AUTOMATION_ENABLED=false

AMAZON_ALLOW_CART=false
AMAZON_ALLOW_PURCHASE=false
EBAY_ALLOW_LIST=false
EBAY_ALLOW_TRACKING=false
```

If a master is false/missing, related write endpoints return **403** and UI shows disabled. Finer flags are ignored unless the master is true.

### Additional runtime gates

1. In-app **Armed** timed window required for any write automation  
2. Purchase confirm: user must type **ASIN** and **max price** as shown — never one-click buy  
3. Caps: max € per order, max € per day, max open Amazon orders  
4. Live recheck must pass or purchase assist blocked  
5. Dry-run mode: log “would cart / would list” without side effects  
6. Audit log for every attempted write  
7. Secrets: browser profile / OAuth tokens; **no plaintext Amazon password in git**; prefer OS-protected storage  

### Phased enablement

| Phase | Capability |
|-------|------------|
| v1 | Credentials-free ops: margin, drafts, manual order desk |
| Next | eBay OAuth read (orders); writes still off |
| Later | Amazon cart fill (`AMAZON_AUTOMATION_ENABLED` + `AMAZON_ALLOW_CART` + Armed) |
| Last | Purchase assist (`AMAZON_ALLOW_PURCHASE`); still typed confirm |

**Recommendation:** keep all masters `false` in `.env.example` and in any shipped default.

---

## 9. sparky2 / Ollama

- Access: `ssh sparky2` → `malicor@192.168.0.72` (`~/.ssh/spark_key`)  
- Models on disk include `agents-a1`, `agents-a1-nonthink`  
- At design time, Ollama CLI could not connect to the server despite systemd “active” — **fix before relying on drafts in production**  
- App config: `OLLAMA_BASE_URL` (e.g. `http://192.168.0.72:11434`) + model name  
- If Ollama unreachable: Evaluate/Order desk still work; draft generation disabled with clear health status  

---

## 10. Repo layout

```text
ai_dropshipping/
  init/                         # reference only — do not ship
  docs/superpowers/specs/       # this design + later plans
  dropship_desk/                # Python: api, margin, amazon, ebay, ollama, safety
  ui/                           # React + Vite
  data/                         # SQLite (gitignored)
  launcher.py
  start.bat
  .env.example
  requirements.txt
```

---

## 11. Error handling

| Failure | Behavior |
|---------|----------|
| Amazon CAPTCHA / parse fail | Candidate rejected; reason stored; no invented prices |
| Ollama down | Draft actions disabled; health shows failure |
| Automation master off | 403 on write routes; UI explains `.env` |
| Recheck fail at order time | DO NOT BUY; confirm disabled |
| Port in use | Launcher finds next free port (ControlAi-style) |

---

## 12. Testing strategy

- **Unit:** margin engine (PASS/FAIL edge cases, fee math, suggested price)  
- **Unit:** safety module (masters, Armed expiry, confirm mismatch, caps)  
- **Integration (optional):** Playwright against a saved HTML fixture, not live Amazon in CI  
- **Manual smoke:** start window → analyze one ASIN → draft with sparky2 → create fulfillment card → recheck  

---

## 13. Build order (implementation sequence)

1. Repo skeleton: FastAPI hello, PyWebView launcher, React shell, `.env.example` with masters false  
2. Margin engine + Settings persistence + Evaluate UI (manual/fixture offer fields first if fetch flaky)  
3. **Find tab: Playwright amazon.de search with discovery criteria → auto-Evaluate survivors**  
4. Amazon offer fetcher (single ASIN deep snapshot) wired to Evaluate / Find enrichment  
5. Ollama draft generation + Drafts screen  
6. Order desk (manual cards + recheck + checklist)  
7. eBay OAuth read (orders) behind `EBAY_AUTOMATION_ENABLED`  
8. Amazon cart assist behind Amazon masters + Armed + confirms  
9. PyInstaller packaging when the above is stable  

---

## 14. Product finder (discovery)

**Decision (2026-08-09):** Own Playwright finder inside Dropship Desk. Clean-room; EbayGlitch is criteria inspiration only — no proprietary code.

### Flow

```text
Find tab → amazon.de search (keyword or auto-niche)
        → SERP parse (ASIN, title, price, stars, reviews)
        → discovery filters
        → light margin Evaluate (search price as amazon_total estimate)
        → save candidates (ready/rejected)
        → stop at hit_target PASS-margin count
```

Deep seller-country / stock / delivery checks run later on product pages for shortlisted ASINs (enrichment), not on every SERP hit in v1.

### Discovery defaults (editable)

| Criterion | Default |
|-----------|---------|
| Min stars | 4.4 |
| Min reviews | 50 |
| Price min–max € | 10–200 (Amazon `p_36` filter) |
| Max delivery days | 10 (detail enrichment) |
| Min stock | >10 when visible (detail) |
| Free shipping | optional |
| Skip sponsored | on |
| Skip sold-by-Amazon | on (detail / badge when visible) |
| Reject DACH sellers | on (detail enrichment) |
| Hit target | 50 margin-PASS candidates |
| Max search pages | 20 |
| Pause between products | ≥800 ms (anti-bot) |
| Modes | manual keyword **or** auto niche term + color |

### UI

New **Find** tab: criteria form, Start/Stop, live log, table of hits with PASS/FAIL, link into Drafts.

### Safety

Finder is **read-only** scraping (not Amazon purchase automation). Still subject to Amazon ToS/CAPTCHA — on CAPTCHA, job stops and UI asks operator to solve / retry. No write masters required.

---

## 15. Open points (resolved enough to build)

| Topic | Decision |
|-------|----------|
| Own stack vs EbayGlitch | Own stack; EG = reference only |
| First loop | Margin → draft → semi-auto fulfill |
| Product discovery | Own Playwright Find tab + criteria above |
| UI | Native Windows app (ControlAi pattern) |
| Amazon/eBay logins | Planned (C); hard `.env` OFF by default |
| Purchase | Never unattended; typed confirm |

No blocking TBD remains for starting the implementation plan after user approves this spec.
