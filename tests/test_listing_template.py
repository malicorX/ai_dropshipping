from dropship_desk.listing_template import apply_listing_template, build_description_html
from dropship_desk.models import ListingShopSettings


def test_build_description_includes_shop_sections():
    shop = ListingShopSettings(shop_name="TestShop", accent_color="#123456")
    html = build_description_html(
        title="Demo Produkt",
        intro_html="<p>Kurze Intro</p>",
        advantages=["A", "B"],
        functions=["F1"],
        scope=["1x Demo"],
        shop=shop,
    )
    assert "TestShop" in html
    assert "Demo Produkt" in html
    assert "Versand" in html
    assert "Rückgabe" in html
    assert "Zahlung" in html
    assert "Feedback" in html
    assert "Kontakt" in html
    assert "#123456" in html
    assert "Kurze Intro" in html


def test_apply_listing_template_from_structured_llm():
    out = apply_listing_template(
        {
            "title": "Hantelset",
            "intro_html": "<p>Starkes Set</p>",
            "advantages": ["Griff", "Gewicht"],
            "functions": ["Verstellbar"],
            "scope_of_delivery": ["2x Hantel"],
        },
        shop=ListingShopSettings(shop_name="X"),
    )
    assert out["listing_template"] == "shop_shell_v1"
    assert "Versand" in out["description_html"]
    assert out["bullet_points"] == ["Griff", "Gewicht"]
