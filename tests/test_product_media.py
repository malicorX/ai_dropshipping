from pathlib import Path

from dropship_desk.product_media import (
    download_product_images,
    normalize_image_url,
    resolve_image_file,
    save_draft_artifacts,
)


def test_normalize_skips_video_overlay():
    assert normalize_image_url(
        "https://m.media-amazon.com/images/I/51Tl0NKtImL.SS40_BG85,85,85_BR-120_PKdp-play-icon-overlay__.jpg"
    ) is None
    assert normalize_image_url("https://m.media-amazon.com/images/I/31GI7Ua3LkL._AC_SL1500_.jpg") == (
        "https://m.media-amazon.com/images/I/31GI7Ua3LkL.jpg"
    )


def test_download_product_images_stores_files(tmp_path, monkeypatch):
    import dropship_desk.config as cfg

    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)

    def fake_pw(asin, pending, timeout=45.0):
        out = []
        for i, url in pending:
            out.append((i, url, b"\xff\xd8\xfffakejpeg", "image/jpeg", None))
        return out

    monkeypatch.setattr(
        "dropship_desk.product_media._fetch_via_playwright",
        fake_pw,
    )

    media = download_product_images(
        "B0TESTIMG01",
        [
            "https://m.media-amazon.com/images/I/abc._AC_.jpg",
            "https://m.media-amazon.com/images/I/def._AC_.jpg",
            "https://m.media-amazon.com/images/I/x.SS40_PKdp-play-icon-overlay__.jpg",
        ],
    )
    assert len(media["local_images"]) == 2
    assert media["local_images"][0]["api_path"].endswith("/01.jpg")
    stored = resolve_image_file("B0TESTIMG01", "01.jpg")
    assert stored is not None
    assert stored.read_bytes().startswith(b"\xff\xd8")

    media2 = download_product_images(
        "B0TESTIMG01",
        ["https://m.media-amazon.com/images/I/abc._AC_.jpg"],
    )
    assert len(media2["local_images"]) == 1


def test_save_draft_artifacts_writes_html_and_json(tmp_path, monkeypatch):
    import dropship_desk.config as cfg

    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)
    media = {
        "local_images": [
            {
                "api_path": "/api/products/B0DRAFT0001/images/01.jpg",
                "path": "images/01.jpg",
                "source_url": "https://example.com/a.jpg",
            }
        ],
        "source_urls": ["https://example.com/a.jpg"],
    }
    arts = save_draft_artifacts(
        "B0DRAFT0001",
        {
            "title": "Test Titel",
            "subtitle": "Sub",
            "bullet_points": ["a", "b"],
            "description_html": "<p>Hallo</p>",
            "model": "test-model",
            "image_plan": {"strategy": "reorder"},
        },
        media,
    )
    html_path = Path(arts["html_path"])
    json_path = Path(arts["json_path"])
    assert html_path.is_file()
    assert json_path.is_file()
    body = html_path.read_text(encoding="utf-8")
    assert "Test Titel" in body
    assert "/api/products/B0DRAFT0001/images/01.jpg" in body
