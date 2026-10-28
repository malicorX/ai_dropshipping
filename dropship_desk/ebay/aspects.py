"""Evidence-based eBay item specifics and category check.

Nothing here invents a value.  An item specific is filled only from facts that
Amazon shows on the product page (title, bullets, spec table) or from an
operator override file.  A required aspect that cannot be proven is reported as
a problem, and the item is not staged: a wrong specific misleads buyers.
"""

from __future__ import annotations

import json
import re
from typing import Any

from dropship_desk.product_media import product_dir

OVERRIDE_FILE = "ebay_overrides.json"
_NUM = r"(\d+(?:[.,]\d+)?)"
_DIMENSIONS = {"länge": "L", "breite": "B", "höhe": "H", "tiefe": "T"}
_FILLER_VALUES = {
    "sonstige",
    "andere",
    "other",
    "nicht zutreffend",
    "siehe beschreibung",
    "keine angabe",
}


class AspectsUnverified(RuntimeError):
    """Required item specifics or the category cannot be proven from the Amazon page."""


def _fold(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).casefold()


def _norm_num(value: str) -> str:
    text = value.replace(",", ".")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def load_overrides(asin: str) -> dict[str, Any]:
    path = product_dir(asin) / OVERRIDE_FILE
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def evidence_text(offer: dict[str, Any]) -> str:
    parts = [str(offer.get("title") or "")]
    parts += [str(b) for b in offer.get("bullets") or []]
    parts += [f"{k}: {v}" for k, v in (offer.get("specs") or {}).items()]
    return "\n".join(parts)


def dimensions(offer: dict[str, Any]) -> tuple[dict[str, str], list[str]]:
    """Labelled cm dimensions (L/B/H/T) all Amazon sources agree on, plus conflicts."""
    found: dict[str, set[str]] = {}

    def add(label: str, value: str) -> None:
        found.setdefault(label, set()).add(_norm_num(value))

    sources = [str(b) for b in offer.get("bullets") or []]
    sources += [str(v) for v in (offer.get("specs") or {}).values()]
    triple = re.compile(
        rf"{_NUM}\s*[x×*]\s*{_NUM}\s*[x×*]\s*{_NUM}\s*cm\s*\(?\s*L\s*[x×*]\s*[WB]\s*[x×*]\s*H",
        re.IGNORECASE,
    )
    lettered = re.compile(rf"(?:{_NUM}\s*[LTBHW]\s*[x×*]\s*)+{_NUM}\s*[LTBHW]\s*cm")
    for text in sources:
        text = text.replace("：", ":")
        for m in triple.finditer(text):
            add("L", m.group(1))
            add("B", m.group(2))
            add("H", m.group(3))
        for m in lettered.finditer(text):
            for value, letter in re.findall(rf"{_NUM}\s*([LTBHW])\b", m.group(0)):
                add("B" if letter == "W" else letter, value)
    out: dict[str, str] = {}
    conflicts: list[str] = []
    for label, values in found.items():
        if len(values) == 1:
            out[label] = f"{next(iter(values))} cm"
        else:
            conflicts.append(f"{label}: {sorted(values)}")
    return out, conflicts


def _allowed(aspect: dict[str, Any]) -> list[str]:
    return [
        str(v.get("localizedValue") or "").strip()
        for v in aspect.get("aspectValues") or []
        if str(v.get("localizedValue") or "").strip()
    ]


def _word_hit(value: str, text: str) -> bool:
    if len(value) < 3:
        return False
    pattern = rf"(?<!\w){re.escape(_fold(value))}(?:s|n|en|e)?(?!\w)"
    return re.search(pattern, text) is not None


def _match_allowed(candidate: str, allowed: list[str]) -> str:
    cand = _fold(candidate)
    for value in allowed:
        if _fold(value) == cand:
            return value
    return ""


def _search_allowed(allowed: list[str], text: str) -> tuple[str, bool]:
    """(value, ambiguous): allowed values that appear as words in the evidence."""
    hits = [v for v in allowed if _fold(v) not in _FILLER_VALUES and _word_hit(v, text)]
    hits = [h for h in hits if not any(h != o and _fold(h) in _fold(o) for o in hits)]
    if len(hits) == 1:
        return hits[0], False
    return "", len(hits) > 1


def resolve_aspects(
    aspect_defs: list[dict[str, Any]],
    offer: dict[str, Any],
    overrides: dict[str, Any] | None = None,
    *,
    category_name: str = "",
    fill_placeholders: bool = False,
) -> tuple[dict[str, list[str]], list[str]]:
    """Return (aspects, problems); problems are required aspects without proof."""
    overrides = overrides or {}
    manual = {_fold(k): v for k, v in (overrides.get("aspects") or {}).items()}
    specs = {_fold(k): str(v).strip() for k, v in (offer.get("specs") or {}).items()}
    text = _fold(evidence_text(offer))
    dims, dim_conflicts = dimensions(offer)
    filled: dict[str, list[str]] = {}
    problems: list[str] = []
    placeholder_for: dict[str, list[str]] = {}
    for aspect in aspect_defs:
        name = str(aspect.get("localizedAspectName") or "").strip()
        if not name:
            continue
        low = _fold(name)
        constraint = aspect.get("aspectConstraint") or {}
        is_brand = "marke" in low or low == "brand"
        is_mpn = "herstellernummer" in low or low in ("mpn", "manufacturer part number")
        if not (constraint.get("aspectRequired") or is_brand or is_mpn):
            continue
        allowed = _allowed(aspect)
        selection_only = str(constraint.get("aspectMode") or "") == "SELECTION_ONLY"
        value = ""

        if low in manual:
            raw = manual[low]
            value = str(raw[0] if isinstance(raw, list) and raw else raw).strip()
        elif is_brand:
            value = specs.get("marke") or specs.get("brand") or specs.get("hersteller") or ""
            value = value or "Markenlos"
        elif is_mpn:
            value = (
                specs.get("herstellernummer")
                or specs.get("modellnummer")
                or specs.get("teilenummer")
                or "Nicht zutreffend"
            )
        elif low in _DIMENSIONS:
            label = _DIMENSIONS[low]
            value = dims.get(label, "")
            if not value:
                conflict = [c for c in dim_conflicts if c.startswith(label)]
                why = (
                    f"widersprüchliche Angaben auf Amazon ({conflict[0]})"
                    if conflict
                    else "nicht auf der Amazon-Seite belegt"
                )
                problems.append(f"{name}: {why}")
                continue
        elif low == "produktart" and not specs.get("produktart"):
            # The product type is the title's own noun that names the category.
            value = _title_noun_for_category(str(offer.get("title") or ""), category_name)
        else:
            spec = specs.get(low, "")
            if spec:
                if allowed and selection_only:
                    value = _match_allowed(spec, allowed)
                    if not value:
                        value, _ = _search_allowed(allowed, _fold(spec))
                else:
                    value = spec
            if not value and allowed:
                value, ambiguous = _search_allowed(allowed, text)
                if ambiguous:
                    problems.append(f"{name}: mehrdeutig auf der Amazon-Seite")
                    continue
        if not value:
            problems.append(f"{name}: nicht auf der Amazon-Seite belegt")
            continue
        if (
            selection_only
            and allowed
            and not (is_brand or is_mpn)
            and not _match_allowed(value, allowed)
        ):
            problems.append(f"{name}: '{value}' ist kein erlaubter eBay-Wert")
            continue
        filled[name] = [value]
    if fill_placeholders:
        remaining: list[str] = []
        for problem in problems:
            name = problem.split(":", 1)[0]
            definition = next(
                (a for a in aspect_defs if str(a.get("localizedAspectName") or "").strip() == name),
                {},
            )
            placeholder = _honest_placeholder(definition)
            if placeholder:
                filled[name] = [placeholder]
            else:
                remaining.append(problem)
        problems = remaining
    return filled, problems


_PLACEHOLDERS = ("Keine Angabe", "Nicht angegeben", "Unbekannt", "Nicht zutreffend")


def _honest_placeholder(aspect: dict[str, Any]) -> str:
    """'Not stated' value eBay accepts, instead of a guess.  Empty if none fits."""
    allowed = _allowed(aspect)
    selection_only = str((aspect.get("aspectConstraint") or {}).get("aspectMode") or "") == "SELECTION_ONLY"
    for wanted in _PLACEHOLDERS:
        for value in allowed:
            if _fold(value) == _fold(wanted):
                return value
    return "" if selection_only else "Keine Angabe"


def _title_noun_for_category(title: str, category_name: str) -> str:
    wanted = re.findall(r"[a-zäöüß]{6,}", _fold(category_name))
    for word in re.findall(r"[A-Za-zÄÖÜäöüß]{6,}", title):
        for target in wanted:
            if _fold(word)[:7] == target[:7]:
                return word
    return ""


def category_fits(title: str, suggestions: list[dict[str, Any]]) -> dict[str, str] | None:
    """First of eBay's top suggestions whose name/ancestors share a word with the title."""

    def stems(text: str) -> set[str]:
        return {w[:6] for w in re.findall(r"[a-zäöüß]{5,}", _fold(text))}

    title_stems = stems(title)
    for sug in suggestions[:5]:
        cat = sug.get("category") or {}
        ancestors = [
            str(a.get("categoryName") or "")
            for a in sug.get("categoryTreeNodeAncestors") or []
        ]
        name = str(cat.get("categoryName") or "")
        names = [name] + ancestors
        if title_stems & stems(" ".join(names)) and cat.get("categoryId"):
            return {
                "category_id": str(cat["categoryId"]),
                "category_name": name,
                "category_path": " > ".join(list(reversed(ancestors)) + [name]),
            }
    return None
