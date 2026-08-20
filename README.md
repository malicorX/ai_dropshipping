# Dropship Desk

Local Windows app for Amazon.de → eBay dropshipping: find/evaluate products, generate listing drafts, then (later) create unpublished eBay offers you approve.

This repository is the source for that tool. The app runs on **your** PC; it is not a hosted SaaS.

## Privacy policy

eBay OAuth and similar integrations: **[PRIVACY.md](./PRIVACY.md)**

Public URL (after this repo is pushed):  
`https://github.com/malicorX/ai_dropshipping/blob/main/PRIVACY.md`

## Spec / plan

- Design: `docs/superpowers/specs/2026-08-09-dropship-desk-design.md`
- Plan: `docs/superpowers/plans/2026-08-09-dropship-desk.md`

## Run

```bat
copy .env.example .env
start.bat
```

Rebuild UI after frontend changes:

```bat
start.bat rebuild
```

Headless API only:

```bat
start.bat headless
```

Then open http://127.0.0.1:8770

Dev UI:

```bat
cd ui && npm install && npm run dev
start.bat dev
```

Tests:

```bat
.venv\Scripts\activate
pip install -r requirements.txt
pytest -q
```

Keep automation flags **false** in `.env` until you deliberately enable them. Do not commit `.env`.
