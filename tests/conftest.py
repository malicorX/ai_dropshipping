import pytest


@pytest.fixture(autouse=True)
def _reset_ebay_env_override():
    import dropship_desk.config as cfg

    cfg.set_ebay_env_override(None)
    yield
    cfg.set_ebay_env_override(None)
