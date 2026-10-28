from dropship_desk import config


def test_ebay_env_defaults_to_sandbox(monkeypatch):
    monkeypatch.delenv("EBAY_ENV", raising=False)
    monkeypatch.setenv("EBAY_SANDBOX_APP_ID", "sbx-app")
    monkeypatch.setenv("EBAY_PROD_APP_ID", "prd-app")
    assert config.ebay_env() == "sandbox"
    assert config.ebay_app_id() == "sbx-app"
    assert "sandbox" in config.ebay_api_base()


def test_ebay_env_production(monkeypatch):
    monkeypatch.setenv("EBAY_ENV", "production")
    monkeypatch.setenv("EBAY_SANDBOX_APP_ID", "sbx-app")
    monkeypatch.setenv("EBAY_PROD_APP_ID", "prd-app")
    assert config.ebay_env() == "production"
    assert config.ebay_app_id() == "prd-app"
    assert config.ebay_api_base() == "https://api.ebay.com"


def test_runtime_override_beats_env_file(monkeypatch):
    monkeypatch.setenv("EBAY_ENV", "sandbox")
    monkeypatch.setenv("EBAY_SANDBOX_APP_ID", "sbx-app")
    monkeypatch.setenv("EBAY_PROD_APP_ID", "prd-app")
    assert config.ebay_env() == "sandbox"
    assert config.set_ebay_env_override("live") == "production"
    assert config.ebay_env() == "production"
    assert config.ebay_app_id() == "prd-app"
    assert config.set_ebay_env_override(None) == "sandbox"
    assert config.ebay_env() == "sandbox"


def test_production_gaps_include_runame(monkeypatch):
    monkeypatch.setenv("EBAY_PROD_APP_ID", "prd-app")
    monkeypatch.setenv("EBAY_PROD_CERT_ID", "prd-cert")
    monkeypatch.delenv("EBAY_PROD_RUNAME", raising=False)
    assert config.ebay_target_ready("production") is False
    assert config.ebay_target_gaps("production") == ["EBAY_PROD_RUNAME"]
    from dropship_desk.ebay.oauth import authorize_url

    monkeypatch.setenv("EBAY_ENV", "sandbox")
    monkeypatch.setenv("EBAY_SANDBOX_APP_ID", "sbx-app")
    monkeypatch.setenv("EBAY_SANDBOX_RUNAME", "")
    try:
        authorize_url()
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "RuName" in str(e)


def test_upload_pin_blocks_live_rest_transport(monkeypatch):
    import pytest

    from dropship_desk.ebay import client as ebay_http

    config.pin_sandbox_for_upload(True)
    try:
        monkeypatch.setattr(config, "ebay_env", lambda: "production")
        constructed: list[str] = []

        class _Client:
            def __init__(self, *args, **kwargs) -> None:
                constructed.append("client")

        monkeypatch.setattr(ebay_http.httpx, "Client", _Client)

        with pytest.raises(RuntimeError, match="LIVE_WRITE_BLOCKED"):
            ebay_http.request(
                "PUT", "/sell/inventory/v1/inventory_item/DD-X", token="token"
            )
        assert constructed == []
    finally:
        config.pin_sandbox_for_upload(False)


def test_upload_pin_checks_before_token_acquisition(monkeypatch):
    import pytest

    from dropship_desk.ebay import client as ebay_http

    config.pin_sandbox_for_upload(True)
    try:
        monkeypatch.setattr(config, "ebay_env", lambda: "production")
        token_calls: list[str] = []

        def _boom() -> str:
            token_calls.append("access_token")
            raise AssertionError("token acquisition must not happen")

        monkeypatch.setattr(ebay_http.ebay_oauth, "access_token", _boom)
        with pytest.raises(RuntimeError, match="LIVE_WRITE_BLOCKED"):
            ebay_http.request("PUT", "/sell/inventory/v1/inventory_item/DD-X")
        assert token_calls == []
    finally:
        config.pin_sandbox_for_upload(False)


def test_upload_pin_allows_sandbox_rest_transport(monkeypatch):
    from dropship_desk.ebay import client as ebay_http

    config.pin_sandbox_for_upload(True)
    try:
        monkeypatch.setattr(config, "ebay_env", lambda: "sandbox")
        calls: list[str] = []

        class _Response:
            status_code = 200
            content = b"{}"
            text = "{}"

            def json(self):
                return {"ok": True}

        class _Client:
            def __init__(self, *args, **kwargs) -> None:
                pass

            def __enter__(self):
                return self

            def __exit__(self, *exc_info) -> bool:
                return False

            def request(self, method, url, **kwargs):
                calls.append(url)
                return _Response()

        monkeypatch.setattr(ebay_http.httpx, "Client", _Client)

        assert ebay_http.request("GET", "/sell/inventory/v1/offer", token="token") == {
            "ok": True
        }
        assert calls == ["https://api.sandbox.ebay.com/sell/inventory/v1/offer"]
    finally:
        config.pin_sandbox_for_upload(False)


def test_upload_pin_blocks_production_media_endpoint(monkeypatch):
    import pytest

    from dropship_desk.ebay import client as ebay_http

    config.pin_sandbox_for_upload(True)
    try:
        monkeypatch.setattr(config, "ebay_env", lambda: "production")
        with pytest.raises(RuntimeError, match="LIVE_WRITE_BLOCKED"):
            ebay_http.media_endpoint()
    finally:
        config.pin_sandbox_for_upload(False)


def _forbid_oauth_http(monkeypatch):
    """Replace oauth.httpx.Client; a guard must raise before construction."""
    from dropship_desk.ebay import oauth

    attempts: list[str] = []

    class _Client:
        def __init__(self, *args, **kwargs) -> None:
            attempts.append("client")

        def __enter__(self):
            return self

        def __exit__(self, *exc_info) -> bool:
            return False

        def post(self, *args, **kwargs):
            attempts.append("post")
            raise AssertionError("OAuth HTTP POST must be blocked before transport")

        def request(self, *args, **kwargs):
            attempts.append("request")
            raise AssertionError("OAuth HTTP request must be blocked before transport")

    monkeypatch.setattr(oauth.httpx, "Client", _Client)
    return attempts


def _production_oauth_env(monkeypatch, tmp_path):
    from dropship_desk.ebay import oauth

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "ebay_env", lambda: "production")
    monkeypatch.setenv("EBAY_PROD_APP_ID", "prd-app")
    monkeypatch.setenv("EBAY_PROD_CERT_ID", "prd-cert")
    monkeypatch.setenv("EBAY_PROD_RUNAME", "prd-runame")
    oauth.clear_application_token_cache()


def test_upload_pin_blocks_exchange_code_before_http(tmp_path, monkeypatch):
    import pytest

    from dropship_desk.ebay import oauth

    config.pin_sandbox_for_upload(True)
    try:
        _production_oauth_env(monkeypatch, tmp_path)
        attempts = _forbid_oauth_http(monkeypatch)
        with pytest.raises(RuntimeError, match="LIVE_WRITE_BLOCKED"):
            oauth.exchange_code("code")
        assert attempts == []
    finally:
        config.pin_sandbox_for_upload(False)


def test_upload_pin_blocks_refresh_access_token_before_http(tmp_path, monkeypatch):
    import pytest

    from dropship_desk.ebay import oauth

    config.pin_sandbox_for_upload(True)
    try:
        _production_oauth_env(monkeypatch, tmp_path)
        attempts = _forbid_oauth_http(monkeypatch)
        with pytest.raises(RuntimeError, match="LIVE_WRITE_BLOCKED"):
            oauth._refresh_access_token("refresh")
        assert attempts == []
    finally:
        config.pin_sandbox_for_upload(False)


def test_upload_pin_blocks_application_token_before_http(tmp_path, monkeypatch):
    import pytest

    from dropship_desk.ebay import oauth

    config.pin_sandbox_for_upload(True)
    try:
        _production_oauth_env(monkeypatch, tmp_path)
        attempts = _forbid_oauth_http(monkeypatch)
        with pytest.raises(RuntimeError, match="LIVE_WRITE_BLOCKED"):
            oauth.application_token()
        assert attempts == []
    finally:
        config.pin_sandbox_for_upload(False)


def test_upload_pin_blocks_picture_upload_before_http(tmp_path, monkeypatch):
    import pytest

    from dropship_desk.ebay import pictures

    config.pin_sandbox_for_upload(True)
    try:
        monkeypatch.setattr(config, "ebay_env", lambda: "production")
        monkeypatch.setattr(
            pictures.ebay_http,
            "media_endpoint",
            lambda: "https://apim.ebay.com/commerce/media/v1_beta/image/create_image_from_file",
        )
        monkeypatch.setattr(pictures.ebay_oauth, "access_token", lambda: "token")
        constructed: list[str] = []

        class _Client:
            def __init__(self, *args, **kwargs) -> None:
                constructed.append("client")

        monkeypatch.setattr(pictures.httpx, "Client", _Client)

        picture = tmp_path / "photo.jpg"
        from PIL import Image

        Image.new("RGB", (8, 8)).save(picture, format="JPEG")
        with pytest.raises(RuntimeError, match="LIVE_WRITE_BLOCKED"):
            pictures._upload_one(picture)
        assert constructed == []
    finally:
        config.pin_sandbox_for_upload(False)
