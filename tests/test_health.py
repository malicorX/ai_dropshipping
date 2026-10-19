from fastapi.testclient import TestClient

from dropship_desk.api import create_app


def test_health_ok(tmp_path, monkeypatch):
    monkeypatch.setenv("DROPSHIP_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("EBAY_AUTOMATION_ENABLED", raising=False)
    monkeypatch.delenv("AMAZON_AUTOMATION_ENABLED", raising=False)
    # Reload config paths used by db — set before create_app
    import dropship_desk.config as cfg

    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cfg, "DB_PATH", tmp_path / "dropship.sqlite3")

    client = TestClient(create_app())
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["automation"]["amazon_enabled"] is False
    assert body["automation"]["ebay_enabled"] is False
