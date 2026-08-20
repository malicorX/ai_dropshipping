"""Hard gates for write automations (env masters)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from dropship_desk import config


class AutomationKind(str, Enum):
    AMAZON_CART = "amazon_cart"
    AMAZON_PURCHASE = "amazon_purchase"
    EBAY_LIST = "ebay_list"
    EBAY_TRACKING = "ebay_tracking"


@dataclass(frozen=True)
class SafetyDecision:
    ok: bool
    reason: str


def check_write_allowed(kind: AutomationKind) -> SafetyDecision:
    """Env-only gate. Armed window is layered on later."""
    if kind is AutomationKind.AMAZON_CART:
        if not config.amazon_automation_enabled():
            return SafetyDecision(False, "AMAZON_AUTOMATION_ENABLED is false")
        if not config.amazon_allow_cart():
            return SafetyDecision(False, "AMAZON_ALLOW_CART is false")
        return SafetyDecision(True, "ok")

    if kind is AutomationKind.AMAZON_PURCHASE:
        if not config.amazon_automation_enabled():
            return SafetyDecision(False, "AMAZON_AUTOMATION_ENABLED is false")
        if not config.amazon_allow_purchase():
            return SafetyDecision(False, "AMAZON_ALLOW_PURCHASE is false")
        return SafetyDecision(True, "ok")

    if kind is AutomationKind.EBAY_LIST:
        if not config.ebay_automation_enabled():
            return SafetyDecision(False, "EBAY_AUTOMATION_ENABLED is false")
        if not config.ebay_allow_list():
            return SafetyDecision(False, "EBAY_ALLOW_LIST is false")
        return SafetyDecision(True, "ok")

    if kind is AutomationKind.EBAY_TRACKING:
        if not config.ebay_automation_enabled():
            return SafetyDecision(False, "EBAY_AUTOMATION_ENABLED is false")
        if not config.ebay_allow_tracking():
            return SafetyDecision(False, "EBAY_ALLOW_TRACKING is false")
        return SafetyDecision(True, "ok")

    exhaustive: never = kind
    raise TypeError(f"unhandled AutomationKind: {exhaustive!r}")
