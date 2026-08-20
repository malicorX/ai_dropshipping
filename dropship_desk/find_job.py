"""Background Find job: Playwright amazon.de search → Evaluate."""

from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from dropship_desk.amazon.search_url import build_search_url
from dropship_desk.amazon.serp import (
    DOM_EXTRACT_JS,
    SerpHit,
    filter_hits,
    hits_from_dom_rows,
    parse_serp_html,
    summarize_hits,
)
from dropship_desk.evaluate_service import offer_from_serp, run_evaluate
from dropship_desk.models import DiscoverySettings, EvaluateRequest

_AUTO_TERMS = [
    "usb c hub",
    "nagelset",
    "küchenhelfer silikon",
    "fahrradlicht set",
    "haustier bürste",
    "werkzeug organizer",
    "camping laterne",
    "schreibtisch organizer",
    "auto handyhalterung",
    "pflanzen sprüher",
]
_COLORS = [
    "schwarz",
    "weiß",
    "grau",
    "blau",
    "grün",
    "rot",
    "beige",
    "koralle",
]

# Soft rate limits — do not hammer amazon.de
_MIN_PAGE_PAUSE_SEC = 4.0
_MAX_PAGE_PAUSE_SEC = 8.0
_EMPTY_FILTER_ABORT_AFTER = 3  # stop if N pages in a row yield 0 usable hits


@dataclass
class FindJobState:
    running: bool = False
    stop_requested: bool = False
    keyword: str = ""
    page: int = 0
    examined: int = 0
    pass_count: int = 0
    reject_count: int = 0
    error: str | None = None
    log: list[str] = field(default_factory=list)
    hits: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "stop_requested": self.stop_requested,
            "keyword": self.keyword,
            "page": self.page,
            "examined": self.examined,
            "pass_count": self.pass_count,
            "reject_count": self.reject_count,
            "error": self.error,
            "log": self.log[-80:],
            "hits": self.hits[-100:],
        }


class FindJobManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.state = FindJobState()
        self._thread: threading.Thread | None = None

    def status(self) -> dict[str, Any]:
        with self._lock:
            return self.state.to_dict()

    def stop(self) -> None:
        with self._lock:
            self.state.stop_requested = True
            self._log("Stop requested")

    def start(self, settings: DiscoverySettings) -> dict[str, Any]:
        with self._lock:
            if self.state.running:
                raise RuntimeError("Find job already running")
            # Clamp aggression server-side regardless of UI
            settings = settings.model_copy(
                update={
                    "max_search_pages": min(settings.max_search_pages, 10),
                    "pause_ms": max(settings.pause_ms, 1200),
                    "hit_target": min(settings.hit_target, 100),
                }
            )
            self.state = FindJobState(running=True)
            keyword = settings.keyword.strip()
            if settings.auto_mode or not keyword:
                keyword = f"{random.choice(_AUTO_TERMS)} {random.choice(_COLORS)}"
            self.state.keyword = keyword
            deleted = 0
            try:
                from dropship_desk.db import prune_rejected

                deleted = prune_rejected(older_than_days=7)
            except Exception:  # noqa: BLE001
                deleted = 0
            self._log(
                f"Starting find: «{keyword}» "
                f"(max {settings.max_search_pages} pages, "
                f"{_MIN_PAGE_PAUSE_SEC:.0f}–{_MAX_PAGE_PAUSE_SEC:.0f}s between pages)"
                + (f"; pruned {deleted} old rejected" if deleted else "")
            )
            self._thread = threading.Thread(
                target=self._run,
                args=(settings, keyword),
                name="find-job",
                daemon=True,
            )
            self._thread.start()
            return self.state.to_dict()

    def _log(self, msg: str) -> None:
        self.state.log.append(msg)

    def _run(self, settings: DiscoverySettings, keyword: str) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except Exception as e:  # noqa: BLE001
            with self._lock:
                self.state.error = f"Playwright import failed: {e}"
                self.state.running = False
                self._log(self.state.error)
            return

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    locale="de-DE",
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/122.0.0.0 Safari/537.36"
                    ),
                )
                page = context.new_page()
                seen: set[str] = set()
                empty_streak = 0

                for page_no in range(1, settings.max_search_pages + 1):
                    with self._lock:
                        if self.state.stop_requested:
                            self._log("Stopped by user")
                            break
                        if self.state.pass_count >= settings.hit_target:
                            self._log("Hit target reached")
                            break
                        self.state.page = page_no

                    if page_no > 1:
                        pause = random.uniform(_MIN_PAGE_PAUSE_SEC, _MAX_PAGE_PAUSE_SEC)
                        with self._lock:
                            self._log(f"Waiting {pause:.1f}s before next page…")
                        time.sleep(pause)

                    url = build_search_url(
                        keyword,
                        price_min_eur=settings.price_min_eur,
                        price_max_eur=settings.price_max_eur,
                        page=page_no,
                    )
                    with self._lock:
                        self._log(f"Open page {page_no}: {url}")

                    page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                    time.sleep(random.uniform(1.5, 3.0))
                    html = page.content()
                    if _looks_like_captcha(html):
                        with self._lock:
                            self.state.error = (
                                "CAPTCHA / bot check — stop. Wait a while, maybe use fewer pages."
                            )
                            self._log(self.state.error)
                        break

                    raw_hits = self._extract_hits(page, html)
                    stats = summarize_hits(raw_hits)
                    hits = filter_hits(
                        raw_hits,
                        min_stars=settings.min_stars,
                        min_reviews=settings.min_reviews,
                        price_min=settings.price_min_eur,
                        price_max=settings.price_max_eur,
                        skip_sponsored=settings.skip_sponsored,
                    )
                    with self._lock:
                        self._log(
                            f"Page {page_no}: {stats['total']} cards "
                            f"(price={stats['with_price']} stars={stats['with_stars']} "
                            f"reviews={stats['with_reviews']} sponsored={stats['sponsored']}) "
                            f"→ {len(hits)} after filters"
                        )

                    if stats["total"] > 0 and len(hits) == 0:
                        empty_streak += 1
                        if empty_streak >= _EMPTY_FILTER_ABORT_AFTER:
                            with self._lock:
                                self.state.error = (
                                    "No products passed filters for several pages "
                                    "(parser missing stars/price, or criteria too strict). Stopping to avoid spam."
                                )
                                self._log(self.state.error)
                            break
                    else:
                        empty_streak = 0

                    for hit in hits:
                        with self._lock:
                            if self.state.stop_requested:
                                break
                            if self.state.pass_count >= settings.hit_target:
                                break
                            if hit.asin in seen:
                                continue
                            seen.add(hit.asin)

                        self._process_hit(hit)
                        time.sleep(
                            max(1.2, settings.pause_ms / 1000.0)
                            + random.uniform(0.0, 1.0)
                        )

                browser.close()
        except Exception as e:  # noqa: BLE001
            with self._lock:
                self.state.error = str(e)
                self._log(f"Find error: {e}")
        finally:
            with self._lock:
                self.state.running = False
                self.state.stop_requested = False
                self._log("Find finished")

    def _extract_hits(self, page: Any, html: str) -> list[SerpHit]:
        try:
            rows = page.evaluate(DOM_EXTRACT_JS)
            if isinstance(rows, list) and rows:
                hits = hits_from_dom_rows(rows)
                if hits:
                    return hits
        except Exception as e:  # noqa: BLE001
            with self._lock:
                self._log(f"DOM extract failed ({e}), falling back to HTML parse")
        return parse_serp_html(html)

    def _process_hit(self, hit: SerpHit) -> None:
        assert hit.price_eur is not None
        offer = offer_from_serp(
            asin=hit.asin,
            title=hit.title,
            price=hit.price_eur,
            url=hit.url,
            stars=hit.stars,
            reviews=hit.reviews,
        )
        result = run_evaluate(
            EvaluateRequest(asin_or_url=hit.asin, offer=offer, save=True),
            persist="pass_only",
        )
        row = {
            "asin": result.asin,
            "title": hit.title,
            "price": hit.price_eur,
            "stars": hit.stars,
            "reviews": hit.reviews,
            "passed": result.passed,
            "status": result.status,
            "candidate_id": result.candidate_id,
            "net_profit": result.margin.get("net_profit"),
        }
        with self._lock:
            self.state.examined += 1
            if result.passed:
                self.state.pass_count += 1
                self._log(
                    f"PASS {hit.asin} €{hit.price_eur:.2f} ★{hit.stars} ({hit.reviews}) → candidate #{result.candidate_id}"
                )
            else:
                self.state.reject_count += 1
                self._log(
                    f"FAIL {hit.asin} €{hit.price_eur:.2f} ★{hit.stars} ({hit.reviews})"
                )
            self.state.hits.append(row)


def _looks_like_captcha(html: str) -> bool:
    low = html.lower()
    return (
        "captcha" in low
        or "robot check" in low
        or "geben sie die zeichen ein" in low
        or "/errors/validatecaptcha" in low
    )


FIND_JOB = FindJobManager()
