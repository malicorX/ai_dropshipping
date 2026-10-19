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
