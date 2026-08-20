"""Ollama client for unique eBay listing copy (sparky2)."""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

from dropship_desk import config
from dropship_desk.listing_template import apply_listing_template

_THINK_BLOCK_RE = re.compile(
    r"<think>[\s\S]*?</(?:think)>|<thinking>[\s\S]*?</thinking>",
    re.IGNORECASE,
)
_THINKING_PROCESS_RE = re.compile(
    r"^\s*thinking process:.*?(?=\n\s*\{|\Z)",
    re.IGNORECASE | re.DOTALL,
)


def ollama_reachable(timeout: float = 2.0) -> bool:
    try:
        r = httpx.get(f"{config.OLLAMA_BASE_URL}/api/tags", timeout=timeout)
        return r.status_code == 200
    except Exception:  # noqa: BLE001
        return False


def generate_listing_draft(
    *,
    amazon_title: str,
    asin: str,
    amazon_price: float,
    ebay_price: float,
    image_urls: list[str] | None = None,
    bullets_hint: str = "",
) -> dict[str, Any]:
    """
    Ask the local LLM for a German eBay listing that is NOT a 1:1 Amazon clone.
    Returns title, subtitle, description_html, bullet_points, image_plan.
    """
    images = image_urls or []
    prompt = f"""Du schreibst ein eBay-Angebot (Deutschland) für Dropshipping.
Regeln (befolgen, aber NICHT im Output wiederholen): kein Amazon-1:1-Klon; eigene Formulierungen;
keine Amazon-Markennamen im Fließtext.

Produktfakten:
- ASIN: {asin}
- Amazon-Titel: {amazon_title}
- Einkaufspreis ca.: {amazon_price:.2f} EUR
- Geplanter eBay-Preis: {ebay_price:.2f} EUR
- Extra-Hinweise: {bullets_hint or "—"}
- Produktbild-URLs ({len(images)}): {json.dumps(images[:8], ensure_ascii=False)}

Gib genau ein JSON-Objekt mit diesen Keys zurück:
{{
  "title": "eBay-Titel max 80 Zeichen, deutsch, verkaufsstark",
  "subtitle": "kurze zweite Zeile max 55 Zeichen",
  "intro_html": "<p>2-4 Sätze Produktvorstellung, eigene Worte, HTML nur mit p/strong/em</p>",
  "advantages": ["5 kurze Vorteile / Verkaufsargumente"],
  "functions": ["5 Funktionen oder technische Details, eigene Worte"],
  "scope_of_delivery": ["1x ... Lieferumfang-Positionen"],
  "image_plan": {{
    "strategy": "1-2 Sätze zur Bildreihenfolge",
    "ordered_urls": ["subset der gegebenen URLs"],
    "skip_urls": [],
    "caption_ideas": ["kurze Alt-Texte"]
  }}
}}

WICHTIG: Nur Produktinhalt. KEIN Versand-, Rückgabe-, Zahlungs-, Feedback- oder Kontakt-Block —
das hängt das System als feste Shop-Vorlage an.
Antworte ausschließlich mit dem JSON-Objekt. Kein Markdown, kein Denken, kein Prolog.
Das erste Zeichen der Antwort muss {{ sein.
"""
    payload = {
        "model": config.OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {
            "temperature": 0.6,
            # Thinking models burn tokens before JSON; leave headroom.
            "num_predict": 4096,
        },
    }
    with httpx.Client(timeout=240.0) as client:
        r = client.post(f"{config.OLLAMA_BASE_URL}/api/generate", json=payload)
        r.raise_for_status()
        data = r.json()
    text = str(data.get("response") or "").strip()
    draft = _parse_json_object(text)
    draft = apply_listing_template(draft)
    draft["model"] = config.OLLAMA_MODEL
    draft["source_asin"] = asin
    draft["source_amazon_title"] = amazon_title
    if "image_plan" not in draft:
        draft["image_plan"] = {
            "strategy": "Andere Bildreihenfolge als Amazon; Hauptbild Lifestyle statt Packshot wenn möglich.",
            "ordered_urls": images[:6],
            "skip_urls": [],
            "caption_ideas": [],
        }
    return draft


def _strip_thinking(text: str) -> str:
    cleaned = _THINK_BLOCK_RE.sub("", text)
    cleaned = _THINKING_PROCESS_RE.sub("", cleaned)
    # Unclosed think tag: drop everything until a JSON object starts.
    cleaned = re.sub(r"<think>[\s\S]*?(?=\{)", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<thinking>[\s\S]*?(?=\{)", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def _extract_json_object(text: str) -> str | None:
    """Find the first balanced {...} object in text."""
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _parse_json_object(text: str) -> dict[str, Any]:
    text = _strip_thinking(text.strip())
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    blob = _extract_json_object(text)
    if not blob:
        raise ValueError(f"LLM did not return JSON: {text[:240]}")
    try:
        obj = json.loads(blob)
    except json.JSONDecodeError as e:
        raise ValueError(f"LLM JSON parse failed: {e}; snippet={blob[:240]}") from e
    if not isinstance(obj, dict):
        raise ValueError("LLM JSON was not an object")
    return obj
