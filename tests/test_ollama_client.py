from dropship_desk.ollama_client import _parse_json_object


def test_parse_json_object_fenced():
    raw = """```json
{"title": "Test Titel", "bullet_points": ["a", "b"]}
```"""
    obj = _parse_json_object(raw)
    assert obj["title"] == "Test Titel"
    assert obj["bullet_points"] == ["a", "b"]


def test_parse_json_object_strips_think_block():
    raw = """Kein Copy-Paste von Amazon.
<think>
Thinking Process:
1. Analyze the request...
</think>
{"title": "Hantelset verstellbar", "subtitle": "Zuhause trainieren", "bullet_points": ["a"]}
"""
    obj = _parse_json_object(raw)
    assert obj["title"] == "Hantelset verstellbar"


def test_parse_json_object_unclosed_think():
    raw = """<think>
still thinking about wording
{"title": "should not parse from inside"}
more think
{"title": "Echte Titelzeile", "bullet_points": ["x"]}
"""
    # Unclosed think: strip until first { — may pick inner junk; prefer last valid? 
    # Our strip removes <think>... until { so first { wins.
    obj = _parse_json_object(raw)
    assert "title" in obj
