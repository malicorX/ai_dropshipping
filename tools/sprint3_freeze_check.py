"""Validate Sprint 3 decisions; this read-only check never authorizes a submit.

Default mode checks the recorded freeze decisions and reports task routing.
--require-live additionally checks the recorded D4 prerequisites. Runtime live
gates, read-back, review and typed confirmation remain separate requirements.
"""

from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import re
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
VALUES = {
    "D1": {"allowed", "denied"},
    "D2": {"accepted", "declined", "after-b0b"},
    "D3": {"waived", "closed"},
    "D4": {"live-1-B0D87HWM4W"},
}
RECORD = re.compile(r"(D[1-4]) \| ([^|]+) \| ([0-9]{4}-[0-9]{2}-[0-9]{2})")
DECISION_START = re.compile(r"^(?:[-*>`]\s*)*(D[0-9]+)", re.IGNORECASE)


def check_decisions(
    path: Path, *, root: Path = REPO_ROOT, require_live: bool = False
) -> tuple[list[str], list[str]]:
    """Return (violations, routing notes), one single-line entry per finding."""
    errors: list[str] = []
    notes: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeError):
        return [f"Cannot read decisions file: {path}"], notes

    seen: set[str] = set()
    decisions: dict[str, str] = {}
    for number, raw in enumerate(lines, start=1):
        line = raw.strip()
        start = DECISION_START.match(line)
        if not start and "|" not in line:
            continue  # Markdown headings, blank lines and explanatory prose.
        key = start.group(1).upper() if start else "decision"
        if key in seen:
            errors.append(f"{key}: duplicate decision at line {number}")
        seen.add(key)
        match = RECORD.fullmatch(line)
        if not match:
            errors.append(f"{key}: malformed line {number}; expected D<n> | value | YYYY-MM-DD (n=1..4)")
            continue
        key, value, recorded_on = match.groups()
        valid = True
        if value not in VALUES[key]:
            errors.append(f"{key}: invalid value at line {number}; expected {' or '.join(sorted(VALUES[key]))}")
            valid = False
        try:
            date.fromisoformat(recorded_on)
        except ValueError:
            errors.append(f"{key}: invalid date at line {number}: {recorded_on}")
            valid = False
        if valid:
            decisions[key] = value

    required = ("D1", "D2", "D3", "D4") if require_live else ("D1", "D2", "D3")
    for key in required:
        if key not in seen:
            errors.append(f"{key}: missing decision")

    if decisions.get("D1") == "denied":
        notes.append("D1 denied blocks all browser tasks and B0b")
    if decisions.get("D2") == "declined":
        notes.append("D2 declined blocks all browser tasks")
    elif decisions.get("D2") == "after-b0b" and decisions.get("D1") == "allowed":
        notes.append("D2 after-b0b: only B0b is permitted; browser tasks remain blocked pending the plan's B0b/risk gates")

    risk_file = path.parent / "sprint3-risk-acceptance.md"
    if (decisions.get("D2") == "accepted" or require_live) and not risk_file.is_file():
        errors.append(f"Missing risk-acceptance file: {risk_file}")

    if require_live:
        for key, expected in (("D1", "allowed"), ("D2", "accepted")):
            if key in decisions and decisions[key] != expected:
                errors.append(f"{key}: --require-live requires {expected}")
        verdict_path = root / "data" / "b0b_verdict.json"
        try:
            content = verdict_path.read_text(encoding="utf-8-sig")
        except FileNotFoundError:
            pass  # B0b is optional when D2 is accepted.
        except (OSError, UnicodeError):
            errors.append(f"Cannot read B0b verdict: {verdict_path}")
        else:
            try:
                verdict = json.loads(content)
                if not isinstance(verdict, dict):
                    raise ValueError("expected a JSON object")
            except ValueError:
                errors.append(f"Invalid B0b verdict JSON object: {verdict_path}")
            else:
                if verdict.get("status") == "PASS":
                    errors.append(f"B0b PASS blocks the live probe: {verdict_path}")

    return errors, notes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help="Repository root for data/b0b_verdict.json and the default decisions path")
    parser.add_argument("--file", type=Path, help="Decisions Markdown file (default: <root>/docs/sprint3-decisions.md)")
    parser.add_argument("--require-live", action="store_true", help="Require the recorded D4 live-probe prerequisites")
    args = parser.parse_args(argv)
    path = args.file if args.file is not None else args.root / "docs" / "sprint3-decisions.md"
    errors, notes = check_decisions(path, root=args.root, require_live=args.require_live)
    for note in notes:
        print(note)
    for error in errors:
        # Keep diagnostics one line even if an overridden filename contains a newline.
        print(error.replace("\r", "\\r").replace("\n", "\\n"), file=sys.stderr)
    return 2 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
