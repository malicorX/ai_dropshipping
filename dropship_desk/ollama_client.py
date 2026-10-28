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
    bullets: list[str] | None = None,
    specs: dict[str, str] | None = None,
) -> dict[str, Any]:
    """
    Ask the local LLM for a German eBay listing that is NOT a 1:1 Amazon clone.
    Returns title, subtitle, description_html, bullet_points, image_plan.
    """
    images = image_urls or []
    bullets = [str(b) for b in (bullets or []) if str(b).strip()]
    specs = {str(k): str(v) for k, v in (specs or {}).items()}
    facts = _facts_block(amazon_title, bullets, specs)
    prompt = f"""Du formulierst ein sachliches eBay-Angebot (Deutschland) NUR aus den unten stehenden Fakten.
Strikte Regeln:
- Verwende ausschließlich Aussagen, die in den Fakten stehen. Erfinde nichts: keine Eigenschaften,
  Materialien, Maße, Zahlen, Lieferumfang, Garantien, Einsatzzwecke oder Wirkungen, die nicht dort stehen.
- Lieber weniger Punkte als ein erfundener Punkt. Wenn die Fakten dünn sind, schreibe kurz.
- Eigene Formulierungen sind erlaubt, aber keine neuen Behauptungen. Keine Marketing-Superlative.
- Keine Amazon-Markennamen im Fließtext.

Fakten (Amazon-Produktseite):
{facts}
- Extra-Hinweise: {bullets_hint or "—"}
- Produktbild-URLs ({len(images)}): {json.dumps(images[:8], ensure_ascii=False)}

Pflicht: Wenn Extra-Hinweise eine Variante/Größe/Farbe nennen, MUSS diese wörtlich im title stehen.

Gib genau ein JSON-Objekt mit diesen Keys zurück:
{{
  "title": "eBay-Titel max 80 Zeichen, deutsch, sachlich, nur Fakten",
  "subtitle": "kurze zweite Zeile max 55 Zeichen, nur Fakten",
  "intro_html": "<p>1-3 Sätze, nur Fakten, HTML nur mit p/strong/em</p>",
  "advantages": ["bis zu 5 kurze Punkte, jeder direkt aus den Fakten"],
  "functions": ["bis zu 5 technische Details, jeder direkt aus den Fakten"],
  "scope_of_delivery": ["nur wenn in den Fakten genannt, sonst leer"],
  "image_plan": {{
    "strategy": "1-2 Sätze zur Bildreihenfolge",
    "ordered_urls": ["subset der gegebenen URLs"],
    "skip_urls": [],
    "caption_ideas": ["kurze Alt-Texte"]
  }}
}}

WICHTIG: Nur Produktinhalt. KEIN Versand-, Rückgabe-, Zahlungs-, Feedback- oder Kontakt-Block.
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
    draft, dropped = enforce_facts(draft, amazon_title, bullets, specs)
    draft = apply_listing_template(draft)
    draft["unsupported_claims_dropped"] = dropped
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


def _facts_block(title: str, bullets: list[str], specs: dict[str, str]) -> str:
    lines = [f"- Titel: {title}"]
    lines += [f"- Merkmal: {b}" for b in bullets[:10]]
    lines += [f"- {k}: {v}" for k, v in specs.items()]
    return "\n".join(lines)


def _stems(text: str) -> set[str]:
    return {w[:6] for w in re.findall(r"[a-zäöüß]{5,}", str(text).casefold())}


def _numbers(text: str) -> set[str]:
    return {n.replace(",", ".") for n in re.findall(r"\d+(?:[.,]\d+)?", str(text))}


def enforce_facts(
    draft: dict[str, Any], title: str, bullets: list[str], specs: dict[str, str]
) -> tuple[dict[str, Any], list[str]]:
    """Drop every generated statement the Amazon facts do not support.

    A line is kept only if every number in it appears in the facts and at least
    60 % of its content words (>=5 letters, by 6-letter stem) do too.  Dropped
    lines are returned so the operator can see what was removed.
    """
    facts = " ".join([title, *bullets, *[f"{k} {v}" for k, v in specs.items()]])
    fact_stems, fact_nums = _stems(facts), _numbers(facts)
    dropped: list[str] = []

    def supported(line: str) -> bool:
        if _numbers(line) - fact_nums:
            return False
        words = _stems(line)
        if not words:
            return True
        return len(words & fact_stems) / len(words) >= 0.6

    out = dict(draft)
    for key in ("advantages", "functions"):
        kept = []
        for item in out.get(key) or []:
            if supported(str(item)):
                kept.append(item)
            else:
                dropped.append(str(item))
        out[key] = kept
    intro = str(out.get("intro_html") or "")
    parts = re.split(r"(?<=[.!?])\s+", re.sub(r"</?(?:p|strong|em)>", " ", intro))
    kept_sent = []
    for sent in (p.strip() for p in parts):
        if not sent:
            continue
        (kept_sent if supported(sent) else dropped).append(sent)
    out["intro_html"] = f"<p>{' '.join(kept_sent)}</p>" if kept_sent else ""
    # Delivery scope only when Amazon states it; never an invented accessory list.
    spec_scope = next(
        (v for k, v in specs.items() if "lieferumfang" in k.casefold() or "packungsinhalt" in k.casefold()),
        "",
    )
    out["scope_of_delivery"] = [spec_scope] if spec_scope else []
    if _numbers(str(out.get("title") or "")) - fact_nums:
        dropped.append(str(out.get("title")))
        out["title"] = title[:80]
    if _numbers(str(out.get("subtitle") or "")) - fact_nums or not supported(str(out.get("subtitle") or "")):
        if out.get("subtitle"):
            dropped.append(str(out.get("subtitle")))
        out["subtitle"] = ""
    return out, dropped
