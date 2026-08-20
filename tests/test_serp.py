from dropship_desk.amazon.search_url import build_search_url
from dropship_desk.amazon.serp import filter_hits, parse_serp_html


def test_build_search_url_price_cents():
    url = build_search_url("baby hocker", price_min_eur=10, price_max_eur=200, page=2)
    assert "amazon.de/s?" in url
    assert "page=2" in url
    assert "p_36%3A1000-20000" in url or "p_36:1000-20000" in url


def test_parse_serp_fixture():
    html = """
    <div data-asin="B0TESTASI1" class="s-result-item">
      <a href="/dp/B0TESTASI1">Super Baby Hocker Holz Premium Qualitaet</a>
      <span aria-label="4,5 von 5 Sternen">4,5 von 5</span>
      <span>128 Bewertungen</span>
      <span class="a-price">€19,99</span>
    </div>
    <div data-asin="B0SPONSOR1" class="s-result-item AdHolder">
      SPONSORED
      <a href="/dp/B0SPONSOR1">Gesponsert Ding</a>
      <span>4,8 von 5 Sternen</span>
      <span>200 Bewertungen</span>
      <span>€25,00</span>
    </div>
    <div data-asin="B0LOWSTAR1" class="s-result-item">
      <a href="/dp/B0LOWSTAR1">Cheap Thing With Long Enough Title Here</a>
      <span>3,2 von 5 Sternen</span>
      <span>80 Bewertungen</span>
      <span>€15,00</span>
    </div>
    """
    hits = parse_serp_html(html)
    asins = {h.asin for h in hits}
    assert "B0TESTASI1" in asins

    filtered = filter_hits(
        hits,
        min_stars=4.4,
        min_reviews=50,
        price_min=10,
        price_max=200,
        skip_sponsored=True,
    )
    assert any(h.asin == "B0TESTASI1" for h in filtered)
    assert all(h.asin != "B0SPONSOR1" for h in filtered)
    assert all(h.asin != "B0LOWSTAR1" for h in filtered)
