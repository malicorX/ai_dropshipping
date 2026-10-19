"""Parse Amazon.de variation (twister) child ASINs from PDP HTML."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

_ASIN_RE = re.compile(r"^[A-Z0-9]{10}$")
_DEFAULT_ASIN_RE = re.compile(
    r'data-defaultasin\s*=\s*["\']([A-Z0-9]{10})["\']',
    re.I,
)


@dataclass(frozen=True)
class VariationChild:
    asin: str
    label: str = ""


def parse_variation_children(html: str, *, current_asin: str = "") -> list[VariationChild]:
    """Return unique child ASINs from twister JSON / swatches. Empty = not a parent."""
    found: dict[str, str] = {}
    current = (current_asin or "").strip().upper()

    for asin, labels in _dimension_display_map(html).items():
        label = " / ".join(str(x).strip() for x in labels if str(x).strip())
        found[asin] = label or found.get(asin, "")

    for asin in _DEFAULT_ASIN_RE.findall(html):
        key = asin.upper()
        found.setdefault(key, "")

    children = [
        VariationChild(asin=asin, label=found[asin])
        for asin in found
        if _ASIN_RE.match(asin)
    ]
    if len(children) <= 1:
        return []
    if current and all(c.asin == current for c in children):
        return []
    children.sort(key=lambda c: (c.label, c.asin))
    return children


def apply_variation_label(title: str, label: str) -> str:
    title = (title or "").strip()
    label = (label or "").strip()
    if not label:
        return title
    if label.lower() in title.lower():
        return title
    if not title:
        return label
    return f"{title} — {label}"


def _dimension_display_map(html: str) -> dict[str, list[str]]:
    raw = _json_object_after_key(html, "dimensionValuesDisplayData")
    if not isinstance(raw, dict):
        return {}
    out: dict[str, list[str]] = {}
    for key, value in raw.items():
        asin = str(key).strip().upper()
        if not _ASIN_RE.match(asin):
            continue
        if isinstance(value, list):
            labels = [str(v).strip() for v in value if str(v).strip()]
        elif value is None:
            labels = []
        else:
            labels = [str(value).strip()]
        out[asin] = labels
    return out


def _json_object_after_key(html: str, key: str) -> object | None:
    token = f'"{key}"'
    start = html.find(token)
    if start < 0:
        return None
    colon = html.find(":", start + len(token))
    if colon < 0:
        return None
    i = colon + 1
    while i < len(html) and html[i].isspace():
        i += 1
    if i >= len(html) or html[i] != "{":
        return None
    blob = _slice_json_object(html, i)
    if not blob:
        return None
    try:
        return json.loads(blob)
    except json.JSONDecodeError:
        return None


def _slice_json_object(text: str, start: int) -> str:
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
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return ""
