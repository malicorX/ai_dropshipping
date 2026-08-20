# Product media + listing draft artifacts

**Date:** 2026-08-09  
**Status:** approved

## Trigger

On **Generate listing draft** only (not Prepare / enrich).

## Images

- Download Amazon PDP image URLs into `data/products/{ASIN}/images/` as `01.*` … `08.*`.
- Skip existing files unless `force_refresh_images` is true.
- Persist `image_urls` (Amazon) + `local_images` (relative paths under product dir) on the candidate offer.
- Serve: `GET /api/products/{asin}/images/{filename}`.

## Draft artifacts

- DB: `listing_draft_json` (unchanged).
- Disk: `data/products/{ASIN}/listing_draft.json` + `listing_draft.html` (preview with local thumbs).

## Flow

PDP refresh (optional) → download images → Ollama draft → save DB + disk artifacts.
