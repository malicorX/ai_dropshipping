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


def test_authorize_url_requires_runame(monkeypatch):
    from dropship_desk.ebay.oauth import authorize_url

    monkeypatch.setenv("EBAY_ENV", "sandbox")
    monkeypatch.setenv("EBAY_SANDBOX_APP_ID", "sbx-app")
    monkeypatch.setenv("EBAY_SANDBOX_RUNAME", "")
    try:
        authorize_url()
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "RuName" in str(e)
