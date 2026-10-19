"""Unit tests for reliable Amazon.de PDP fetching (no network).

The Playwright launcher, navigation and sleep are stubbed.  Every test runs
against fake browser objects; no Chrome process is started.
"""

from __future__ import annotations

import threading
import time

import pytest

import dropship_desk.amazon.product as product

ASIN = "B0TEST0001"
ASIN2 = "B0TEST0002"
CHILD1 = "B0CHILD001"
CHILD2 = "B0CHILD002"
CHILD3 = "B0CHILD003"
PRICE_HTML = "<html><body><span id='productTitle'>Test</span></body></html>"
RAW = {"title": "Test product", "price": "€ 19,99", "stars": "4,6 von 5", "reviews": "123"}

# Clearly a block/interstitial: tiny document with no product-title node and
# no "not found" title, so it stays retryable.
BLOCK_HTML = (
    "<html><head><title>Amazon.de</title></head>"
    "<body><p>Something went wrong.</p></body></html>"
)
# Amazon's terminal "this ASIN does not exist / was delisted" pages (~2 KB).
NOT_FOUND_HTML_DE = (
    "<html><head><title>Seite wurde nicht gefunden</title></head>"
    "<body><h1>Seite wurde nicht gefunden</h1></body></html>"
)
NOT_FOUND_HTML_EN = (
    "<html><head><title>Page Not Found</title></head>"
    "<body><h1>Page Not Found</h1></body></html>"
)
# A real (large) page with a product title, but no buy box/price.
NO_PRICE_HTML = (
    "<html><body>"
    + ("<div>filler</div>" * 2_000)
    + '<span id="productTitle">Real but unavailable product</span>'
    + "</body></html>"
)


class FakePage:
    def __init__(self, html: str = PRICE_HTML, raw: dict | None = None) -> None:
        self.html = html
        self.raw = RAW if raw is None else raw

    def content(self) -> str:
        return self.html

    def evaluate(self, _script: str) -> dict:
        return self.raw


class FakeContext:
    def __init__(self, page: FakePage) -> None:
        self._page = page

    def new_page(self) -> FakePage:
        return self._page


class FakeBrowser:
    def __init__(self, page: FakePage) -> None:
        self._page = page
        self.closed = False

    def new_context(self, **_kwargs) -> FakeContext:
        return FakeContext(self._page)

    def close(self) -> None:
        self.closed = True


class FakePlaywright:
    def __enter__(self):
        return object()

    def __exit__(self, *_exc):
        return False


class Clock:
    """Fake monotonic clock advanced by fake sleeps."""

    def __init__(self) -> None:
        self.now = 1_000.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += max(0.0, seconds)


class Harness:
    def __init__(self, monkeypatch):
        self.clock = Clock()
        self.launches = 0
        self.goto_calls = 0
        self.page = FakePage()
        # Optional per-attempt pages, consumed one launch at a time.
        self.pages: list[FakePage] = []
        self.launch_error: BaseException | None = None
        self.goto_errors: list[BaseException] = []
        self._monkeypatch = monkeypatch

        monkeypatch.setattr(product, "_playwright", lambda: FakePlaywright())
        monkeypatch.setattr(product, "_launch_browser", self._launch)
        monkeypatch.setattr(product, "_goto", self._goto)
        monkeypatch.setattr(product.time, "sleep", self.clock.sleep)
        monkeypatch.setattr(product.time, "monotonic", self.clock.monotonic)

    def _launch(self, _pw):
        self.launches += 1
        if self.launch_error is not None:
            raise self.launch_error
        page = self.pages.pop(0) if self.pages else self.page
        return FakeBrowser(page)

    def _goto(self, _page, _url):
        self.goto_calls += 1
        if self.goto_errors:
            raise self.goto_errors.pop(0)


@pytest.fixture(autouse=True)
def _fresh_fetch_state():
    product.reset_fetch_state()
    yield
    product.reset_fetch_state()


@pytest.fixture
def harness(monkeypatch):
    return Harness(monkeypatch)


def test_success_on_first_try_uses_one_launch(harness):
    offer = product.fetch_product_offer(ASIN)

    assert offer.asin == ASIN
    assert offer.amazon_total == pytest.approx(19.99)
    assert harness.launches == 1
    assert harness.goto_calls == 1
    assert harness.clock.sleeps == []


def test_connection_reset_is_retried_then_succeeds(harness):
    harness.goto_errors = [RuntimeError("net::ERR_CONNECTION_RESET at https://www.amazon.de/")]

    offer = product.fetch_product_offer(ASIN)

    assert offer.amazon_total == pytest.approx(19.99)
    assert harness.launches == 2
    assert harness.goto_calls == 2
    assert len(harness.clock.sleeps) == 1
    assert 5.0 <= harness.clock.sleeps[0] <= 6.0


def test_three_connection_resets_raise_amazon_unreachable(harness):
    harness.goto_errors = [RuntimeError("net::ERR_CONNECTION_RESET") for _ in range(3)]

    with pytest.raises(product.AmazonUnreachable) as excinfo:
        product.fetch_product_offer(ASIN)

    message = str(excinfo.value)
    assert message.startswith("AMAZON_UNREACHABLE")
    assert ASIN in message
    assert "3" in message
    assert "RuntimeError" in message
    assert harness.launches == 3
    assert len(harness.clock.sleeps) == 2


def test_timeout_is_retried(harness):
    harness.goto_errors = [TimeoutError("Timeout 60000ms exceeded")]

    offer = product.fetch_product_offer(ASIN)

    assert offer.amazon_total == pytest.approx(19.99)
    assert harness.launches == 2
    assert len(harness.clock.sleeps) == 1


def test_captcha_is_not_retried(harness):
    harness.page = FakePage(html="<html>Please enter the characters you see: captcha</html>")

    with pytest.raises(RuntimeError) as excinfo:
        product.fetch_product_offer(ASIN)

    assert not isinstance(excinfo.value, product.AmazonUnreachable)
    assert "CAPTCHA" in str(excinfo.value)
    assert harness.launches == 1
    assert harness.goto_calls == 1
    assert harness.clock.sleeps == []


@pytest.mark.parametrize(
    "html",
    [
        NOT_FOUND_HTML_DE,
        NOT_FOUND_HTML_EN,
        "<html><head><title>SEITE WURDE NICHT GEFUNDEN</title></head><body></body></html>",
    ],
    ids=["de", "en", "de-uppercase"],
)
def test_not_found_page_is_terminal_non_retryable(harness, html):
    harness.page = FakePage(html=html, raw={"title": "", "price": None})

    with pytest.raises(product.AsinNotFound) as excinfo:
        product.fetch_product_offer(ASIN)

    message = str(excinfo.value)
    assert message.startswith(f"ASIN_NOT_FOUND: {ASIN}")
    assert not isinstance(excinfo.value, product.AmazonUnreachable)
    assert harness.launches == 1
    assert harness.goto_calls == 1
    assert harness.clock.sleeps == []
    assert product._consecutive_failures == 0


def test_not_found_does_not_reset_existing_consecutive_failure_counter(harness):
    product._consecutive_failures = 7
    harness.page = FakePage(html=NOT_FOUND_HTML_DE, raw={"title": "", "price": None})

    with pytest.raises(product.AsinNotFound):
        product.fetch_product_offer(ASIN)

    assert product._consecutive_failures == 7
    assert harness.launches == 1


def test_25_consecutive_not_found_asins_do_not_trip_failure_cap(harness):
    harness.page = FakePage(html=NOT_FOUND_HTML_DE, raw={"title": "", "price": None})

    for _ in range(25):
        with pytest.raises(product.AsinNotFound):
            product.fetch_product_offer(ASIN)

    assert product._consecutive_failures == 0
    assert harness.launches == 25

    # The cap is 20: if not-found had incremented (or reset then incremented)
    # the counter, the 26th call would fail before launching.
    with pytest.raises(product.AsinNotFound):
        product.fetch_product_offer(ASIN)

    assert harness.launches == 26


def test_block_page_is_retried_three_times_then_unreachable_names_blocked_page(harness):
    harness.page = FakePage(html=BLOCK_HTML, raw={"title": "", "price": None})

    with pytest.raises(product.AmazonUnreachable) as excinfo:
        product.fetch_product_offer(ASIN)

    message = str(excinfo.value)
    assert message.startswith("AMAZON_UNREACHABLE")
    assert ASIN in message
    assert "blocked_page" in message
    assert "3" in message
    assert harness.launches == 3
    assert harness.goto_calls == 3
    assert len(harness.clock.sleeps) == 2
    assert all(5.0 <= seconds <= 6.0 for seconds in harness.clock.sleeps)


def test_block_page_then_good_page_succeeds_on_second_attempt(harness):
    harness.pages = [
        FakePage(html=BLOCK_HTML, raw={"title": "", "price": None}),
        FakePage(),
    ]

    offer = product.fetch_product_offer(ASIN)

    assert offer.amazon_total == pytest.approx(19.99)
    assert harness.launches == 2
    assert harness.goto_calls == 2
    assert len(harness.clock.sleeps) == 1
    assert 5.0 <= harness.clock.sleeps[0] <= 6.0


def test_full_page_without_price_is_not_retried(harness):
    harness.page = FakePage(
        html=NO_PRICE_HTML,
        raw={"title": "Real but unavailable product", "price": ""},
    )

    with pytest.raises(RuntimeError) as excinfo:
        product.fetch_product_offer(ASIN)

    assert not isinstance(excinfo.value, product.AmazonUnreachable)
    assert "Could not parse product price" in str(excinfo.value)
    assert harness.launches == 1
    assert harness.goto_calls == 1
    assert harness.clock.sleeps == []


def test_chrome_missing_is_distinct_from_amazon_unreachable(harness):
    harness.launch_error = RuntimeError(
        "browserType.launch: Chromium distribution 'chrome' is not found at "
        "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"
    )

    with pytest.raises(product.ChromeNotFound) as excinfo:
        product.fetch_product_offer(ASIN)

    assert not isinstance(excinfo.value, product.AmazonUnreachable)
    assert str(excinfo.value).startswith("CHROME_NOT_FOUND")
    assert harness.launches == 1
    assert harness.clock.sleeps == []


def test_failure_cap_default_is_20_and_stops_before_launching_the_21st_fetch(harness):
    # Pin the real default so raising it (e.g. to 2000) fails this test.
    assert product.MAX_CONSECUTIVE_FAILURES == 20

    harness.page = FakePage(html="<html>captcha</html>")

    for _ in range(20):
        with pytest.raises(RuntimeError) as excinfo:
            product.fetch_product_offer(ASIN)
        assert not isinstance(excinfo.value, product.AmazonUnreachable)

    assert harness.launches == 20

    with pytest.raises(product.AmazonUnreachable) as excinfo:
        product.fetch_product_offer(ASIN)

    assert str(excinfo.value).startswith("AMAZON_UNREACHABLE: failure cap reached")
    assert harness.launches == 20


def test_success_resets_consecutive_failure_counter(harness):
    harness.page = FakePage(html="<html>captcha</html>")
    for _ in range(product.MAX_CONSECUTIVE_FAILURES - 1):
        with pytest.raises(RuntimeError):
            product.fetch_product_offer(ASIN)

    # A success clears the counter ...
    harness.page = FakePage()
    assert product.fetch_product_offer(ASIN).amazon_total == pytest.approx(19.99)

    # ... so another full run of terminal failures is allowed to launch.
    harness.page = FakePage(html="<html>captcha</html>")
    for _ in range(product.MAX_CONSECUTIVE_FAILURES):
        with pytest.raises(RuntimeError) as excinfo:
            product.fetch_product_offer(ASIN)
        assert not isinstance(excinfo.value, product.AmazonUnreachable)

    assert harness.launches == (product.MAX_CONSECUTIVE_FAILURES - 1) + 1 + product.MAX_CONSECUTIVE_FAILURES


def test_min_gap_is_enforced_between_two_asins(harness):
    product.fetch_product_offer(ASIN)
    assert harness.clock.sleeps == []

    product.fetch_product_offer(ASIN2)

    assert len(harness.clock.sleeps) == 1
    assert harness.clock.sleeps[0] == pytest.approx(product.MIN_GAP_SEC)
    assert harness.launches == 2


def test_launch_browser_uses_installed_chrome_channel():
    class FakeChromium:
        def __init__(self) -> None:
            self.kwargs: dict | None = None

        def launch(self, **kwargs):
            self.kwargs = kwargs
            return object()

    class FakePW:
        def __init__(self) -> None:
            self.chromium = FakeChromium()

    p = FakePW()
    product._launch_browser(p)

    assert p.chromium.kwargs is not None
    assert p.chromium.kwargs["channel"] == "chrome"
    assert p.chromium.kwargs["headless"] is True


# ---------------------------------------------------------------------------
# Round 4: thread safety, half-open failure cap, variation child failures.
# ---------------------------------------------------------------------------


def test_fetch_lock_serialises_two_threads_and_enforces_min_gap(monkeypatch):
    """Two concurrent fetches must not launch together or violate MIN_GAP.

    Uses real sleeps (the fake Clock is not thread-aware). The first fake
    browser is held open for 400 ms while the second thread is started; with no
    lock the second launch overlaps it, while the lock forces a full wait.
    """
    monkeypatch.setattr(product, "MIN_GAP_SEC", 0.15)

    state = {"in_flight": 0, "max_in_flight": 0}
    state_lock = threading.Lock()
    launch_times: list[float] = []
    first_launched = threading.Event()

    class _Page:
        def content(self):
            return PRICE_HTML

        def evaluate(self, _script):
            return RAW

    class _Context:
        def new_page(self):
            return _Page()

    class _Browser:
        def new_context(self, **_kwargs):
            return _Context()

        def close(self):
            with state_lock:
                state["in_flight"] -= 1

    class _Playwright:
        def __enter__(self):
            return object()

        def __exit__(self, *_exc):
            return False

    def launch(_pw):
        with state_lock:
            state["in_flight"] += 1
            state["max_in_flight"] = max(
                state["max_in_flight"], state["in_flight"]
            )
            launch_times.append(time.monotonic())
        first_launched.set()
        time.sleep(0.4)
        return _Browser()

    monkeypatch.setattr(product, "_playwright", lambda: _Playwright())
    monkeypatch.setattr(product, "_launch_browser", launch)
    monkeypatch.setattr(product, "_goto", lambda _page, _url: None)

    errors: list[BaseException] = []

    def worker():
        try:
            product.fetch_product_offer(ASIN)
        except BaseException as exc:  # noqa: BLE001 - re-asserted below
            errors.append(exc)

    first = threading.Thread(target=worker)
    second = threading.Thread(target=worker)
    first.start()
    assert first_launched.wait(timeout=5)
    second.start()
    first.join(timeout=10)
    second.join(timeout=10)

    assert not first.is_alive() and not second.is_alive()
    assert errors == []
    assert len(launch_times) == 2
    gap = abs(launch_times[1] - launch_times[0])
    assert gap >= product.MIN_GAP_SEC - 0.02
    assert state["max_in_flight"] == 1


def test_failure_cap_default_cooldown_is_600_seconds():
    assert product.CAP_COOLDOWN_SEC == 600


def test_failure_cap_half_opens_after_cooldown(harness):
    harness.page = FakePage(html="<html>captcha</html>")

    for _ in range(product.MAX_CONSECUTIVE_FAILURES):
        with pytest.raises(RuntimeError) as excinfo:
            product.fetch_product_offer(ASIN)
        assert not isinstance(excinfo.value, product.AmazonUnreachable)

    assert harness.launches == 20
    assert product._consecutive_failures == 20

    # 599 s after the last terminal failure the breaker is still open.
    harness.clock.now += product.CAP_COOLDOWN_SEC - 1
    with pytest.raises(product.AmazonUnreachable) as excinfo:
        product.fetch_product_offer(ASIN)
    assert str(excinfo.value).startswith("AMAZON_UNREACHABLE: failure cap reached")
    assert harness.launches == 20

    # 601 s after it half-opens: the counter resets and a healthy fetch runs.
    harness.clock.now += 2
    harness.page = FakePage()
    offer = product.fetch_product_offer(ASIN)

    assert offer.amazon_total == pytest.approx(19.99)
    assert product._consecutive_failures == 0
    assert harness.launches == 21


def _variation_parent_page() -> FakePage:
    raw = dict(RAW)
    raw["children"] = [
        {"asin": CHILD1, "label": "Small"},
        {"asin": CHILD2, "label": "Medium"},
        {"asin": CHILD3, "label": "Large"},
    ]
    return FakePage(html=PRICE_HTML, raw=raw)


def _offer_for(asin: str):
    return product._offer_from_raw(asin, f"https://www.amazon.de/dp/{asin}", RAW)


def test_variation_child_failure_cap_error_is_re_raised(harness, monkeypatch):
    harness.page = _variation_parent_page()
    calls: list[str] = []

    def fake_fetch(asin: str):
        calls.append(asin)
        if asin == CHILD2:
            raise product.AmazonUnreachable(
                "AMAZON_UNREACHABLE: failure cap reached after 20 consecutive "
                f"terminal failures; refusing ASIN {asin}"
            )
        return _offer_for(asin)

    monkeypatch.setattr(product, "fetch_product_offer", fake_fetch)

    with pytest.raises(product.AmazonUnreachable) as excinfo:
        product.fetch_variation_offers(ASIN)

    assert str(excinfo.value).startswith("AMAZON_UNREACHABLE: failure cap reached")
    # Child 3 is never attempted once the cap aborts the list.
    assert calls == [CHILD1, CHILD2]


def test_variation_child_chrome_not_found_is_re_raised(harness, monkeypatch):
    harness.page = _variation_parent_page()

    def fake_fetch(_asin: str):
        raise product.ChromeNotFound("CHROME_NOT_FOUND: chrome executable missing")

    monkeypatch.setattr(product, "fetch_product_offer", fake_fetch)

    with pytest.raises(product.ChromeNotFound):
        product.fetch_variation_offers(ASIN)


def test_variation_child_asin_not_found_is_skipped(harness, monkeypatch):
    harness.page = _variation_parent_page()
    calls: list[str] = []

    def fake_fetch(asin: str):
        calls.append(asin)
        if asin == CHILD2:
            raise product.AsinNotFound(f"ASIN_NOT_FOUND: {asin}")
        return _offer_for(asin)

    monkeypatch.setattr(product, "fetch_product_offer", fake_fetch)

    offers = product.fetch_variation_offers(ASIN)

    assert [offer.asin for offer in offers] == [CHILD1, CHILD3]
    assert calls == [CHILD1, CHILD2, CHILD3]


def test_variation_child_fetches_are_paced_through_fetch_product_offer(harness):
    harness.pages = [
        _variation_parent_page(),
        FakePage(),
        FakePage(),
        FakePage(),
    ]

    offers = product.fetch_variation_offers(ASIN)

    assert [offer.asin for offer in offers] == [CHILD1, CHILD2, CHILD3]
    assert harness.launches == 4

    # Each child first pays the explicit child pause, then fetch_product_offer
    # -> _load_pdp -> _pace_asin_load must sleep the MIN_GAP remainder. A child
    # call straight to _load_pdp_once would never produce this sleep.
    remainder = product.MIN_GAP_SEC - product._CHILD_PAUSE_SEC
    assert remainder > 0
    paced_sleeps = [
        seconds
        for seconds in harness.clock.sleeps
        if seconds == pytest.approx(remainder)
    ]
    assert len(paced_sleeps) >= 2
