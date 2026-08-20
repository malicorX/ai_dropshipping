"""Pure margin math for Amazon → eBay dropship decisions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MarginInputs:
    amazon_total: float
    ebay_price: float
    ebay_fee_pct: float = 0.15
    ebay_fee_fixed: float = 0.35
    buffer_eur: float = 3.0
    min_margin_eur: float = 5.0
    min_margin_pct: float = 0.50


@dataclass(frozen=True)
class MarginResult:
    ebay_fees: float
    net_proceeds: float
    net_profit: float
    margin_pct: float
    passed: bool
    fail_reasons: tuple[str, ...]


def _money(value: float) -> float:
    return round(value + 1e-9, 2)


def evaluate_margin(inp: MarginInputs) -> MarginResult:
    if inp.amazon_total <= 0:
        return MarginResult(
            ebay_fees=0.0,
            net_proceeds=0.0,
            net_profit=0.0,
            margin_pct=0.0,
            passed=False,
            fail_reasons=("amazon_total must be > 0",),
        )
    if inp.ebay_price <= 0:
        return MarginResult(
            ebay_fees=0.0,
            net_proceeds=0.0,
            net_profit=0.0,
            margin_pct=0.0,
            passed=False,
            fail_reasons=("ebay_price must be > 0",),
        )

    ebay_fees = _money(inp.ebay_price * inp.ebay_fee_pct + inp.ebay_fee_fixed)
    net_proceeds = _money(inp.ebay_price - ebay_fees)
    net_profit = _money(net_proceeds - inp.amazon_total - inp.buffer_eur)
    margin_pct = net_profit / inp.amazon_total

    reasons: list[str] = []
    if net_profit < inp.min_margin_eur:
        reasons.append(
            f"net_profit {net_profit:.2f} < min_margin_eur {inp.min_margin_eur:.2f}"
        )
    if margin_pct < inp.min_margin_pct:
        reasons.append(
            f"margin_pct {margin_pct:.4f} < min_margin_pct {inp.min_margin_pct:.4f}"
        )

    return MarginResult(
        ebay_fees=ebay_fees,
        net_proceeds=net_proceeds,
        net_profit=net_profit,
        margin_pct=margin_pct,
        passed=not reasons,
        fail_reasons=tuple(reasons),
    )


def suggest_ebay_price(
    amazon_total: float,
    *,
    fee_pct: float = 0.15,
    fee_fixed: float = 0.35,
    buffer_eur: float = 3.0,
    min_margin_eur: float = 5.0,
    min_margin_pct: float = 0.50,
) -> float:
    """Smallest psychological *.99 price that PASSes margin rules."""
    if amazon_total <= 0:
        raise ValueError("amazon_total must be > 0")

    # Lower bound from both absolute and percent floors.
    need_profit = max(min_margin_eur, amazon_total * min_margin_pct)
    # ebay_price - fee_pct*ebay_price - fee_fixed - amazon - buffer >= need_profit
    # ebay_price * (1 - fee_pct) >= need_profit + amazon + buffer + fee_fixed
    denominator = 1.0 - fee_pct
    if denominator <= 0:
        raise ValueError("fee_pct must be < 1")
    raw = (need_profit + amazon_total + buffer_eur + fee_fixed) / denominator

    # Search upward from ceil to *.99 until PASS (handles rounding).
    candidate = _snap_99(raw)
    for _ in range(500):
        result = evaluate_margin(
            MarginInputs(
                amazon_total=amazon_total,
                ebay_price=candidate,
                ebay_fee_pct=fee_pct,
                ebay_fee_fixed=fee_fixed,
                buffer_eur=buffer_eur,
                min_margin_eur=min_margin_eur,
                min_margin_pct=min_margin_pct,
            )
        )
        if result.passed:
            return candidate
        candidate = _money(candidate + 1.0)
        candidate = _snap_99(candidate)
    raise RuntimeError("could not find passing ebay price")


def _snap_99(value: float) -> float:
    """Round up to next x.99 (or keep if already *.99 and >= value)."""
    whole = int(value)
    snapped = _money(whole + 0.99)
    if snapped + 1e-9 < value:
        snapped = _money(whole + 1 + 0.99)
    return snapped
