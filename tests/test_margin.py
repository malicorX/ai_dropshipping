from dropship_desk.margin import MarginInputs, evaluate_margin, suggest_ebay_price


def test_margin_pass_known_case():
    # amazon 20, ebay needs ~50% → roughly mid-40s+
    result = evaluate_margin(
        MarginInputs(amazon_total=20.0, ebay_price=55.0)
    )
    assert result.passed
    assert result.net_profit >= 5.0
    assert result.margin_pct >= 0.50


def test_margin_fail_low_profit():
    result = evaluate_margin(
        MarginInputs(amazon_total=20.0, ebay_price=25.0)
    )
    assert not result.passed
    assert any("net_profit" in r or "margin_pct" in r for r in result.fail_reasons)


def test_suggest_price_passes_when_reevaluated():
    amazon = 18.5
    price = suggest_ebay_price(amazon)
    result = evaluate_margin(MarginInputs(amazon_total=amazon, ebay_price=price))
    assert result.passed
    assert str(price).endswith(".99") or abs(price % 1 - 0.99) < 1e-6
