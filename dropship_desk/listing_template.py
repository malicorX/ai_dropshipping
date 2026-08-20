"""Static eBay description shell + editable shop boilerplate."""

from __future__ import annotations

import html
import json
from typing import Any

from dropship_desk.db import connect, init_db
from dropship_desk.models import ListingShopSettings


def get_listing_shop_settings() -> ListingShopSettings:
    init_db()
    with connect() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?", ("listing_shop",)
        ).fetchone()
    if not row:
        return ListingShopSettings()
    return ListingShopSettings.model_validate_json(row["value"])


def set_listing_shop_settings(settings: ListingShopSettings) -> ListingShopSettings:
    init_db()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO settings(key, value) VALUES(?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            ("listing_shop", settings.model_dump_json()),
        )
    return settings


def build_description_html(
    *,
    title: str,
    intro_html: str,
    advantages: list[str],
    functions: list[str],
    scope: list[str],
    shop: ListingShopSettings | None = None,
) -> str:
    """Compose full eBay description: product body + static shop sections."""
    shop = shop or get_listing_shop_settings()
    accent = html.escape(shop.accent_color or "#0f6e56")
    shop_name = html.escape(shop.shop_name or "Shop")
    safe_title = html.escape(title or "")

    def bullets(items: list[str]) -> str:
        lis = "".join(f"<li>{html.escape(str(x))}</li>" for x in items if str(x).strip())
        return f"<ul>{lis}</ul>" if lis else "<ul><li>—</li></ul>"

    intro = (intro_html or "").strip() or f"<p>{safe_title}</p>"

    product = f"""
<section class="dd-product">
  <h1 class="dd-title">{safe_title}</h1>
  <div class="dd-intro">{intro}</div>
  <h2>Vorteile</h2>
  {bullets(advantages)}
  <h2>Funktionen &amp; Details</h2>
  {bullets(functions)}
  <h2>Lieferumfang</h2>
  {bullets(scope)}
  {shop.photo_disclaimer_html}
</section>
"""

    shop_block = f"""
<section class="dd-shop">
  <details class="dd-acc" open>
    <summary>Versand</summary>
    <div class="dd-acc-body">{shop.shipping_html}</div>
  </details>
  <details class="dd-acc">
    <summary>Rückgabe</summary>
    <div class="dd-acc-body">{shop.returns_html}</div>
  </details>
  <details class="dd-acc">
    <summary>Zahlung</summary>
    <div class="dd-acc-body">{shop.payment_html}</div>
  </details>
  <details class="dd-acc">
    <summary>Feedback</summary>
    <div class="dd-acc-body">{shop.feedback_html}</div>
  </details>
  <details class="dd-acc">
    <summary>Kontakt</summary>
    <div class="dd-acc-body">{shop.contact_html}</div>
  </details>
</section>
"""

    return f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8" />
<style>
  .dd-wrap {{
    max-width: 720px;
    margin: 0 auto;
    padding: 16px 14px 28px;
    font-family: Arial, Helvetica, sans-serif;
    color: #1a1a1a;
    line-height: 1.45;
    background: #fff;
    border: 1px solid #e5e7eb;
  }}
  .dd-brand {{
    font-size: 12px;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    color: {accent};
    font-weight: 700;
    margin-bottom: 10px;
  }}
  .dd-title {{
    font-size: 22px;
    margin: 0 0 12px;
    color: #111;
    border-bottom: 3px solid {accent};
    padding-bottom: 8px;
  }}
  .dd-product h2 {{
    font-size: 16px;
    margin: 18px 0 8px;
    color: {accent};
  }}
  .dd-product ul {{
    margin: 0 0 8px 18px;
    padding: 0;
  }}
  .dd-product li {{ margin: 4px 0; }}
  .dd-note {{
    margin-top: 14px;
    font-size: 13px;
    color: #555;
    background: #f4f7f6;
    padding: 10px 12px;
    border-left: 3px solid {accent};
  }}
  .dd-shop {{ margin-top: 22px; }}
  .dd-acc {{
    border: 1px solid #ddd;
    margin-bottom: 8px;
    background: #fafafa;
  }}
  .dd-acc summary {{
    cursor: pointer;
    list-style: none;
    padding: 12px 14px;
    font-weight: 700;
    background: {accent};
    color: #fff;
  }}
  .dd-acc summary::-webkit-details-marker {{ display: none; }}
  .dd-acc-body {{
    padding: 12px 14px;
    background: #fff;
    font-size: 14px;
  }}
  .dd-acc-body ul {{ margin: 0 0 0 18px; padding: 0; }}
  .dd-acc-body li {{ margin: 6px 0; }}
  .dd-foot {{
    margin-top: 16px;
    font-size: 11px;
    color: #888;
    text-align: center;
  }}
</style>
</head>
<body>
<div class="dd-wrap">
  <div class="dd-brand">{shop_name}</div>
  {product}
  {shop_block}
  <div class="dd-foot">{shop_name} · Angebotstext</div>
</div>
</body>
</html>
"""


def apply_listing_template(draft: dict[str, Any], shop: ListingShopSettings | None = None) -> dict[str, Any]:
    """
    Take LLM product fields and produce final description_html + bullet_points.
    Accepts either new structured fields or legacy description_html.
    """
    shop = shop or get_listing_shop_settings()
    title = str(draft.get("title") or "").strip()
    advantages = _as_str_list(draft.get("advantages") or draft.get("bullet_points") or [])
    functions = _as_str_list(draft.get("functions") or [])
    scope = _as_str_list(draft.get("scope_of_delivery") or draft.get("lieferumfang") or [])
    intro = str(draft.get("intro_html") or "").strip()

    if not intro and draft.get("description_html"):
        intro = str(draft.get("description_html"))

    if not functions and advantages:
        functions = list(advantages[:3])
    if not scope:
        scope = [f"1x {title}" if title else "1x Artikel laut Angebot"]

    if intro.startswith("<"):
        intro_html = intro
    else:
        intro_html = f"<p>{html.escape(intro)}</p>" if intro else f"<p>{html.escape(title)}</p>"

    description_html = build_description_html(
        title=title,
        intro_html=intro_html,
        advantages=advantages,
        functions=functions,
        scope=scope,
        shop=shop,
    )
    out = dict(draft)
    out["description_html"] = description_html
    out["bullet_points"] = advantages
    out["advantages"] = advantages
    out["functions"] = functions
    out["scope_of_delivery"] = scope
    out["intro_html"] = intro
    out["listing_template"] = "shop_shell_v1"
    out["shop_name"] = shop.shop_name
    return out


def _as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                value = parsed
            else:
                return [value] if value.strip() else []
        except json.JSONDecodeError:
            return [value] if value.strip() else []
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    return [str(value).strip()] if str(value).strip() else []
