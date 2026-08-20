import pytest

from dropship_desk.safety import AutomationKind, check_write_allowed


@pytest.fixture(autouse=True)
def _clear_automation_env(monkeypatch):
    for key in (
        "AMAZON_AUTOMATION_ENABLED",
        "AMAZON_ALLOW_CART",
        "AMAZON_ALLOW_PURCHASE",
        "EBAY_AUTOMATION_ENABLED",
        "EBAY_ALLOW_LIST",
        "EBAY_ALLOW_TRACKING",
    ):
        monkeypatch.delenv(key, raising=False)


def test_all_kinds_denied_by_default():
    for kind in AutomationKind:
        decision = check_write_allowed(kind)
        assert decision.ok is False


def test_amazon_cart_requires_master_and_flag(monkeypatch):
    monkeypatch.setenv("AMAZON_AUTOMATION_ENABLED", "true")
    assert check_write_allowed(AutomationKind.AMAZON_CART).ok is False
    monkeypatch.setenv("AMAZON_ALLOW_CART", "true")
    assert check_write_allowed(AutomationKind.AMAZON_CART).ok is True
    assert check_write_allowed(AutomationKind.AMAZON_PURCHASE).ok is False
