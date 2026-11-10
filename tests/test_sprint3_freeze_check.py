"""Exercise the freeze gate through its CLI, without browser or eBay access."""

import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "sprint3_freeze_check.py"
LINES = {
    "D1": "D1 | allowed | 2026-11-10",
    "D2": "D2 | accepted | 2026-11-10",
    "D3": "D3 | waived | 2026-11-10",
    "D4": "D4 | live-1-B0D87HWM4W | 2026-11-10",
}


@pytest.fixture
def decision_file(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    path = docs / "sprint3-decisions.md"
    path.write_text("\n".join(LINES.values()) + "\n", encoding="utf-8")
    (docs / "sprint3-risk-acceptance.md").write_text("Accepted\n", encoding="utf-8")
    return path


def run_check(path, live=False, *, root=None):
    command = [sys.executable, str(TOOL), "--file", str(path), "--root", str(root or path.parent.parent)]
    if live:
        command.append("--require-live")
    return subprocess.run(command, capture_output=True, text=True, cwd=path.parent, check=False)


def replace_line(path, decision, replacement):
    path.write_text(path.read_text(encoding="utf-8").replace(LINES[decision], replacement), encoding="utf-8")


def assert_violation(result, *messages):
    assert result.returncode == 2, result.stdout + result.stderr
    assert "Traceback" not in result.stderr
    for message in messages:
        assert message in result.stderr


@pytest.mark.parametrize("live", [False, True], ids=["default", "live"])
def test_valid_decisions(decision_file, live):
    result = run_check(decision_file, live)
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""


@pytest.mark.parametrize("live", [False, True])
@pytest.mark.parametrize("decision", ["D1", "D2", "D3"])
def test_deleted_decision(decision_file, live, decision):
    replace_line(decision_file, decision, "")
    assert_violation(run_check(decision_file, live), decision)


@pytest.mark.parametrize("live", [False, True])
@pytest.mark.parametrize("decision", LINES)
@pytest.mark.parametrize("damage", ["separator", "date", "value", "trailing"])
def test_garbled_decision(decision_file, live, decision, damage):
    line = LINES[decision]
    if damage == "separator":
        line = line.replace(" | ", " : ")
    elif damage == "date":
        line = line.replace("2026-11-10", "2026-02-30")
    elif damage == "value":
        line = f"{decision} | undecided | 2026-11-10"
    else:
        line += " extra"
    replace_line(decision_file, decision, line)
    assert_violation(run_check(decision_file, live), decision)


@pytest.mark.parametrize("live", [False, True])
@pytest.mark.parametrize("decision", LINES)
def test_duplicate_decision(decision_file, live, decision):
    with decision_file.open("a", encoding="utf-8") as stream:
        stream.write(LINES[decision] + "\n")
    assert_violation(run_check(decision_file, live), decision, "duplicate")


@pytest.mark.parametrize("live", [False, True])
def test_d4_wrong_asin(decision_file, live):
    replace_line(decision_file, "D4", "D4 | live-1-B000000000 | 2026-11-10")
    assert_violation(run_check(decision_file, live), "D4", "live-1-B0D87HWM4W")


@pytest.mark.parametrize("live", [False, True])
def test_d4_absent(decision_file, live):
    replace_line(decision_file, "D4", "")
    result = run_check(decision_file, live)
    if live:
        assert_violation(result, "D4")
    else:
        assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("live", [False, True])
def test_missing_risk_file(decision_file, live):
    (decision_file.parent / "sprint3-risk-acceptance.md").unlink()
    assert_violation(run_check(decision_file, live), "sprint3-risk-acceptance.md")


@pytest.mark.parametrize("live", [False, True])
def test_risk_must_be_a_file(decision_file, live):
    risk = decision_file.parent / "sprint3-risk-acceptance.md"
    risk.unlink()
    risk.mkdir()
    assert_violation(run_check(decision_file, live), "sprint3-risk-acceptance.md")


@pytest.mark.parametrize("decision,value,message", [
    ("D1", "denied", "blocks all browser tasks and B0b"),
    ("D2", "declined", "blocks all browser tasks"),
    ("D2", "after-b0b", "only B0b is permitted"),
])
@pytest.mark.parametrize("live", [False, True])
def test_routing(decision_file, live, decision, value, message):
    replace_line(decision_file, decision, f"{decision} | {value} | 2026-11-10")
    if decision == "D2":
        (decision_file.parent / "sprint3-risk-acceptance.md").unlink()
    result = run_check(decision_file, live)
    assert message in result.stdout
    if live:
        assert_violation(result, decision)
    else:
        assert result.returncode == 0, result.stderr


def test_denied_takes_precedence_over_after_b0b(decision_file):
    replace_line(decision_file, "D1", "D1 | denied | 2026-11-10")
    replace_line(decision_file, "D2", "D2 | after-b0b | 2026-11-10")
    result = run_check(decision_file)
    assert result.returncode == 0, result.stderr
    assert "blocks all browser tasks and B0b" in result.stdout
    assert "only B0b is permitted" not in result.stdout


@pytest.mark.parametrize("live", [False, True])
@pytest.mark.parametrize("status", ["PASS", "FAIL", "UNKNOWN"])
def test_b0b_verdict(decision_file, live, status):
    data = decision_file.parent.parent / "data"
    data.mkdir()
    (data / "b0b_verdict.json").write_text(json.dumps({"status": status}), encoding="utf-8")
    result = run_check(decision_file, live)
    if live and status == "PASS":
        assert_violation(result, "b0b_verdict.json", "PASS")
    else:
        assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("content", ["{broken", "[]", "null"])
def test_unreadable_verdict_fails_closed(decision_file, content):
    data = decision_file.parent.parent / "data"
    data.mkdir()
    (data / "b0b_verdict.json").write_text(content, encoding="utf-8")
    assert_violation(run_check(decision_file, True), "b0b_verdict.json")


def test_root_override_and_risk_relative_to_decisions(decision_file, tmp_path):
    root = tmp_path / "different-root"
    (root / "data").mkdir(parents=True)
    (root / "data" / "b0b_verdict.json").write_text('{"status": "PASS"}', encoding="utf-8")
    assert_violation(run_check(decision_file, True, root=root), "PASS")
    (root / "data" / "b0b_verdict.json").unlink()
    assert run_check(decision_file, True, root=root).returncode == 0
    (decision_file.parent / "sprint3-risk-acceptance.md").unlink()
    (root / "docs").mkdir()
    (root / "docs" / "sprint3-risk-acceptance.md").write_text("Wrong directory", encoding="utf-8")
    assert_violation(run_check(decision_file, True, root=root), "sprint3-risk-acceptance.md")


@pytest.mark.parametrize("live", [False, True])
@pytest.mark.parametrize("date", ["2026-2-01", "20261110", "0000-01-01", "2025-02-29"])
def test_invalid_date_format_or_calendar(decision_file, live, date):
    replace_line(decision_file, "D1", f"D1 | allowed | {date}")
    assert_violation(run_check(decision_file, live), "D1")


def test_leap_day_and_closed_review_with_markdown_prose(decision_file):
    text = "# Decisions\n\nThe D1 decision means drafts only; D4 is separate.\n\n"
    # Prose mentioning decisions must not be mistaken for a decision record.
    text += "\n".join(LINES.values()).replace("2026-11-10", "2024-02-29").replace("waived", "closed")
    decision_file.write_text(text + "\n", encoding="utf-8")
    assert run_check(decision_file, True).returncode == 0


def test_each_violation_has_one_stderr_line(decision_file):
    replace_line(decision_file, "D1", "D1 | perhaps | 2026-11-10")
    replace_line(decision_file, "D3", "D3 | pending | 2026-11-10")
    result = run_check(decision_file)
    assert_violation(result, "D1", "D3")
    assert len(result.stderr.splitlines()) == 2


@pytest.mark.parametrize("live", [False, True])
def test_missing_decisions_file(decision_file, live):
    decision_file.unlink()
    assert_violation(run_check(decision_file, live), "sprint3-decisions.md")


def test_root_sets_default_decisions_path(decision_file):
    replace_line(decision_file, "D2", "")
    result = subprocess.run([sys.executable, str(TOOL), "--root", str(decision_file.parent.parent)], capture_output=True, text=True, check=False)
    assert_violation(result, "D2")


def test_repository_decisions_pass_default_gate(tmp_path):
    # Every pytest landing validates the committed decisions, from any cwd.
    result = subprocess.run([sys.executable, str(TOOL)], cwd=tmp_path, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
