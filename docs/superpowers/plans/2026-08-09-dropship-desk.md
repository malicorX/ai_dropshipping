# Dropship Desk Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a Windows desktop app (PyWebView + FastAPI + React) that evaluates Amazon.de ASINs for eBay dropship margin, drafts listings via sparky2 Ollama, and runs a semi-auto order desk — with Amazon/eBay write automation hard-off via `.env`.

**Architecture:** Local FastAPI on `127.0.0.1` serves JSON APIs and (in prod) the Vite build; `launcher.py` opens PyWebView. Domain logic lives in `dropship_desk/` (margin, safety, db, amazon fetch, ollama). UI is three screens: Evaluate, Drafts, Order desk (+ Settings).

**Tech Stack:** Python 3.11+, FastAPI, uvicorn, pywebview, pydantic, python-dotenv, SQLite, Playwright (later tasks), React 18 + Vite + TypeScript, pytest, httpx.

**Spec:** `docs/superpowers/specs/2026-08-09-dropship-desk-design.md`

## Global Constraints

- Windows-first; bind API to `127.0.0.1` only.
- Do not copy EbayGlitch proprietary code from `init/`; clean-room only.
- Default `.env` masters: `AMAZON_AUTOMATION_ENABLED=false`, `EBAY_AUTOMATION_ENABLED=false`, and all finer allow flags `false`.
- No plaintext Amazon/eBay passwords in git.
- Margin defaults: fee 15%, fixed €0.35, buffer €3, min €5, min 20% of amazon_total.
- aiRouter / THE SEVEN: available later for reviews; not required for v1 app features.
- Do not commit unless the user asks.

---

## File map

| Path | Responsibility |
|------|----------------|
| `dropship_desk/__init__.py` | Package version |
| `dropship_desk/config.py` | Load `.env`, paths, Ollama URL, automation masters |
| `dropship_desk/safety.py` | `automation_allowed(kind)` gate |
| `dropship_desk/margin.py` | Pure margin math + PASS/FAIL |
| `dropship_desk/db.py` | SQLite schema + settings/candidates/drafts/orders |
| `dropship_desk/amazon/fetch.py` | Single-ASIN offer snapshot (Playwright) |
| `dropship_desk/ollama_client.py` | Listing draft via sparky2 |
| `dropship_desk/api.py` | FastAPI routes + static UI mount |
| `launcher.py` | Uvicorn + PyWebView |
| `start.bat` | venv, deps, optional Vite, launch |
| `ui/` | React screens |
| `tests/` | pytest |
| `.env.example` | Documented flags |
| `.gitignore` | venv, data, dist, node_modules |

---

### Task 1: Repo skeleton + health API + launcher

**Files:**
- Create: `dropship_desk/__init__.py`, `dropship_desk/config.py`, `dropship_desk/api.py`, `launcher.py`, `requirements.txt`, `.env.example`, `.gitignore`, `start.bat`, `tests/test_health.py`

**Interfaces:**
- Produces: `create_app() -> FastAPI`, `GET /api/health` → `{status, version, frozen, automation: {...}}`
- Produces: `config.load_settings()` with masters and `OLLAMA_BASE_URL`

- [ ] **Step 1: Write failing health test**

```python
# tests/test_health.py
from fastapi.testclient import TestClient
from dropship_desk.api import create_app

def test_health_ok():
    client = TestClient(create_app())
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["automation"]["amazon_enabled"] is False
    assert body["automation"]["ebay_enabled"] is False
```

- [ ] **Step 2: Run test — expect fail (import/module missing)**

Run: `pytest tests/test_health.py -v`

- [ ] **Step 3: Implement skeleton**

`dropship_desk/config.py`: load dotenv from repo root; expose `RUNTIME_ROOT`, `DATA_DIR`, bool helpers for masters (default False).

`dropship_desk/api.py`: `create_app()` with `/api/health`.

`launcher.py`: find free port from 8770, start uvicorn thread, `--dev` → `http://localhost:5173`, else serve UI from app, `--headless` supported, PyWebView title `Dropship Desk`.

`requirements.txt`: fastapi, uvicorn, python-dotenv, pydantic, pywebview, httpx, pytest, playwright.

`.env.example`: all automation flags false; `OLLAMA_BASE_URL=http://192.168.0.72:11434`; `OLLAMA_MODEL=agents-a1`.

`start.bat`: create `.venv`, pip install, if `dev` start note for Vite, run `python launcher.py`.

- [ ] **Step 4: pytest passes**

- [ ] **Step 5: Skip commit** (unless user asks)

---

### Task 2: Margin engine

**Files:**
- Create: `dropship_desk/margin.py`, `tests/test_margin.py`

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True)
class MarginInputs:
    amazon_total: float
    ebay_price: float
    ebay_fee_pct: float = 0.15
    ebay_fee_fixed: float = 0.35
    buffer_eur: float = 3.0
    min_margin_eur: float = 5.0
    min_margin_pct: float = 0.20

@dataclass(frozen=True)
class MarginResult:
    ebay_fees: float
    net_proceeds: float
    net_profit: float
    margin_pct: float
    passed: bool
    fail_reasons: tuple[str, ...]

def evaluate_margin(inp: MarginInputs) -> MarginResult: ...
def suggest_ebay_price(amazon_total: float, *, fee_pct=0.15, fee_fixed=0.35, buffer_eur=3.0, min_margin_eur=5.0, min_margin_pct=0.20) -> float: ...
```

- [ ] **Step 1: Failing tests** — known PASS case, FAIL on low profit, FAIL on low %, `suggest_ebay_price` returns value that PASSes when re-evaluated.

- [ ] **Step 2: Implement `margin.py`** — round money to 2 decimals; suggest price search upward then snap to `*.99` if still PASS.

- [ ] **Step 3: pytest `tests/test_margin.py` PASS**

---

### Task 3: Safety module

**Files:**
- Create: `dropship_desk/safety.py`, `tests/test_safety.py`

**Interfaces:**
- Produces: `AutomationKind` literal/enum: `amazon_cart | amazon_purchase | ebay_list | ebay_tracking`
- Produces: `check_write_allowed(kind: AutomationKind) -> SafetyDecision` with `ok: bool`, `reason: str`
- Masters: amazon kinds require `AMAZON_AUTOMATION_ENABLED` and matching `AMAZON_ALLOW_*`; ebay kinds require `EBAY_AUTOMATION_ENABLED` and matching `EBAY_ALLOW_*`.

- [ ] **Step 1–3:** TDD — default env → all kinds denied; with masters+flags true → allowed (Armed window added in Task 7; for Task 3 only env gates).

---

### Task 4: SQLite + Evaluate API (fixture offer)

**Files:**
- Create: `dropship_desk/db.py`, `dropship_desk/models.py`
- Modify: `dropship_desk/api.py`
- Create: `tests/test_evaluate_api.py`

**Interfaces:**
- `POST /api/evaluate` body `{asin_or_url, ebay_price?, max_amazon_buy?, offer?}`  
  If `offer` omitted, use stub offer for v1 until Task 5 (`amazon_total` required in stub path via optional manual fields).  
  For Task 4: accept explicit `offer: {title, amazon_total, ...}` so UI/tests work without Playwright.
- `GET /api/settings`, `PUT /api/settings`
- DB tables: `settings` (JSON blob), `candidates`

- [ ] **Step 1–3:** TDD evaluate PASS/FAIL persistence; settings round-trip.

---

### Task 5: React UI shell + Evaluate screen

...

### Task 5b: Find tab (Playwright discovery) — DONE 2026-08-09

**Files:** `dropship_desk/amazon/*`, `find_job.py`, `evaluate_service.py`, Find UI, `/api/find/*`

- Discovery criteria defaults: stars ≥4.4, reviews ≥50, €10–200, skip sponsored, hit target 50
- SERP parse + margin Evaluate; CAPTCHA stops job
- Tests: `tests/test_serp.py`

---

### Task 6: Amazon offer fetcher (Playwright)

**Files:**
- Create: `dropship_desk/amazon/__init__.py`, `dropship_desk/amazon/fetch.py`, `dropship_desk/amazon/parse.py`
- Modify: `POST /api/evaluate` to fetch when `offer` omitted
- Tests: parse fixture HTML from `tests/fixtures/amazon_product.html` (captured sample; no live Amazon in CI)

---

### Task 7: Ollama drafts + Drafts screen

**Files:**
- Create: `dropship_desk/ollama_client.py`
- Routes: `POST /api/candidates/{id}/draft`, `GET /api/candidates`
- UI Drafts screen wired
- Health includes `ollama_reachable`

---

### Task 8: Order desk + recheck

**Files:**
- Routes for fulfillment cards CRUD, `POST .../recheck`, `POST .../confirm-placed`
- UI Order desk
- Enforce `max_amazon_buy` / DO NOT BUY

---

### Task 9: Armed window + automation stubs

**Files:**
- Extend `safety.py` with timed Armed session in memory/SQLite
- Stub endpoints that 403 when masters off; when on+Armed, still require typed ASIN+price for purchase
- Settings UI shows master flags (read-only from health)

---

### Task 10: Packaging polish

**Files:**
- Harden `start.bat`, README with run instructions
- Optional PyInstaller later (out of critical path)

---

## Spec coverage check

| Spec section | Tasks |
|--------------|-------|
| Windows shell | 1, 5, 10 |
| Margin rules | 2, 4 |
| Screens | 5, 7, 8 |
| `.env` masters / C automation | 3, 9 |
| sparky2 Ollama | 7 |
| Amazon fetch | 6 |
| Order recheck | 8 |
| No EbayGlitch fork | Global |
| aiRouter | Out of scope (noted) |

## Execution

User directed: **build now** → **Inline execution** in this session (executing-plans style), starting Task 1.
