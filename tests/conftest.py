import pytest


@pytest.fixture(autouse=True)
def _reset_ebay_env_override(tmp_path, monkeypatch):
    import dropship_desk.config as cfg

    # Never read the operator's real .env from tests.  A non-existent path also
    # means "no .env file ever existed", so flag tests use process env alone
    # unless they explicitly install a temporary .env file.
    monkeypatch.setattr(cfg, "ENV_FILE", tmp_path / "no-such-dotenv", raising=False)
    cfg.clear_live_env_cache()
    # load_dotenv at import copies the operator's real .env gate values into
    # os.environ; tests must start with every live gate closed.
    for key in ("EBAY_LIVE_UPLOAD_ENABLED", "EBAY_AUTOMATION_ENABLED", "EBAY_ALLOW_LIST"):
        monkeypatch.delenv(key, raising=False)

    cfg.set_ebay_env_override(None)
    cfg.pin_sandbox_for_upload(False)
    cfg.pin_production_for_live(False)
    yield
    # A test may monkeypatch cfg.ebay_env with a function that raises during
    # its own teardown window; clearing the override must not mask that.
    try:
        cfg.set_ebay_env_override(None)
    except Exception:  # noqa: BLE001 - the override is already cleared
        cfg._ebay_env_override = None
    cfg.pin_sandbox_for_upload(False)
    cfg.pin_production_for_live(False)
    cfg.clear_live_env_cache()
