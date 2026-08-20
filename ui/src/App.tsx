import { useCallback, useEffect, useRef, useState } from "react";

type Tab = "find" | "evaluate" | "drafts" | "orders" | "settings";

type Health = {
  status: string;
  version: string;
  automation: {
    amazon_enabled: boolean;
    ebay_enabled: boolean;
  };
  ollama_base_url: string;
  ebay?: {
    env: string;
    app_id_set: boolean;
    cert_id_set: boolean;
    runame_set: boolean;
    oauth_connected: boolean;
    app_id_hint: string;
    auto_publish: boolean;
    sell_allowed?: boolean;
    sell_block_reason?: string;
  };
};

type EbayListing = {
  asin?: string;
  env?: string;
  status: string;
  sku?: string;
  offer_id?: string;
  listing_id?: string;
  item_url?: string;
  seller_hub_url?: string;
  category_id?: string;
  category_name?: string;
  error?: string;
};

type ListingDraft = {
  title?: string;
  subtitle?: string;
  bullet_points?: string[];
  description_html?: string;
  image_plan?: {
    strategy?: string;
    ordered_urls?: string[];
    skip_urls?: string[];
    caption_ideas?: string[];
  };
  model?: string;
  media?: {
    local_images?: { api_path?: string; source_url?: string; path?: string }[];
    source_urls?: string[];
    download_errors?: string[];
  };
  artifacts?: {
    html_api?: string;
    json_api?: string;
    html_path?: string;
    json_path?: string;
  };
};

type EvaluateResult = {
  asin: string;
  ebay_price: number;
  max_amazon_buy: number;
  suggested_ebay_price: number;
  passed: boolean;
  hard_reject_reasons: string[];
  margin: {
    ebay_fees: number;
    net_proceeds: number;
    net_profit: number;
    margin_pct: number;
    passed: boolean;
    fail_reasons: string[];
  };
  candidate_id: number | null;
  status: string;
  offer: { title: string; amazon_total: number };
};

type Candidate = {
  id: number;
  asin: string;
  title: string;
  amazon_total: number;
  ebay_price: number;
  status: string;
  created_at: string;
  updated_at: string;
  offer?: {
    stars?: number | null;
    reviews?: number | null;
    price_source?: string;
    note?: string;
  };
  listing_draft?: ListingDraft | null;
  ebay_listing?: EbayListing | null;
};

type MarginSettings = {
  ebay_fee_pct: number;
  ebay_fee_fixed: number;
  buffer_eur: number;
  min_margin_eur: number;
  min_margin_pct: number;
  max_delivery_days: number;
  min_stock: number;
  skip_sold_by_amazon: boolean;
  reject_dach_sellers: boolean;
};

type ListingShopSettings = {
  shop_name: string;
  accent_color: string;
  shipping_html: string;
  returns_html: string;
  payment_html: string;
  feedback_html: string;
  contact_html: string;
  photo_disclaimer_html: string;
};

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) {
    const text = await res.text();
    try {
      const parsed = JSON.parse(text) as { detail?: unknown };
      if (typeof parsed.detail === "string" && parsed.detail) {
        throw new Error(parsed.detail);
      }
    } catch (e) {
      if (e instanceof Error && e.message && e.message !== text) {
        throw e;
      }
    }
    throw new Error(text || res.statusText);
  }
  return res.json() as Promise<T>;
}

type ListingSeed = {
  asin: string;
  title: string;
  amazonTotal: number;
  ebayPrice?: number;
  sellerCountry?: string;
};

function amazonUrl(asin: string): string {
  return `https://www.amazon.de/dp/${asin}`;
}

async function openAmazon(asin: string): Promise<void> {
  await api<{ ok: boolean }>("/api/open-external", {
    method: "POST",
    body: JSON.stringify({ url: amazonUrl(asin) }),
  });
}

async function openExternal(url: string): Promise<void> {
  await api<{ ok: boolean }>("/api/open-external", {
    method: "POST",
    body: JSON.stringify({ url }),
  });
}

export default function App() {
  const [tab, setTab] = useState<Tab>("find");
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string>("");
  const [listingSeed, setListingSeed] = useState<ListingSeed | null>(null);

  const prepareListing = useCallback((seed: ListingSeed) => {
    setListingSeed(seed);
    setTab("evaluate");
    setError("");
  }, []);

  const refreshHealth = useCallback(async (): Promise<Health | null> => {
    try {
      const h = await api<Health>("/api/health");
      setHealth(h);
      return h;
    } catch (e) {
      setHealth(null);
      setError(e instanceof Error ? e.message : String(e));
      return null;
    }
  }, []);

  useEffect(() => {
    void refreshHealth();
    const id = window.setInterval(() => {
      void refreshHealth();
    }, 20000);
    return () => window.clearInterval(id);
  }, [refreshHealth]);

  return (
    <div className="app">
      <header className="top">
        <h1>Dropship Desk</h1>
        <div className="health">
          {health
            ? `v${health.version} · API ok · Amazon auto ${health.automation.amazon_enabled ? "ON" : "off"} · eBay auto ${health.automation.ebay_enabled ? "ON" : "off"}`
            : "API unreachable"}
        </div>
      </header>

      <nav className="tabs">
        {(
          [
            ["find", "Find"],
            ["evaluate", "Evaluate"],
            ["drafts", "Drafts"],
            ["orders", "Order desk"],
            ["settings", "Settings"],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            className={tab === id ? "active" : ""}
            onClick={() => setTab(id)}
          >
            {label}
          </button>
        ))}
      </nav>

      {tab === "find" && (
        <FindPanel onError={setError} onPrepareListing={prepareListing} />
      )}
      {tab === "evaluate" && (
        <EvaluatePanel
          onError={setError}
          seed={listingSeed}
          onSeedConsumed={() => setListingSeed(null)}
        />
      )}
      {tab === "drafts" && (
        <DraftsPanel onError={setError} onPrepareListing={prepareListing} />
      )}
      {tab === "orders" && (
        <div className="panel muted">
          Order desk lands next. Flow: Find → Drafts → Prepare listing → Evaluate → Send unpublished
          offer to eBay → Publish (manual).
        </div>
      )}
      {tab === "settings" && (
        <SettingsPanel onError={setError} health={health} refreshHealth={refreshHealth} />
      )}

      {error ? <p className="error">{error}</p> : null}
    </div>
  );
}

type FindStatus = {
  running: boolean;
  keyword: string;
  page: number;
  examined: number;
  pass_count: number;
  reject_count: number;
  error: string | null;
  log: string[];
  hits: Array<{
    asin: string;
    title: string;
    price: number;
    stars: number | null;
    reviews: number | null;
    passed: boolean;
    status: string;
    candidate_id: number | null;
    net_profit: number | null;
  }>;
};

function FindPanel({
  onError,
  onPrepareListing,
}: {
  onError: (msg: string) => void;
  onPrepareListing: (seed: ListingSeed) => void;
}) {
  const [keyword, setKeyword] = useState("");
  const [autoMode, setAutoMode] = useState(false);
  const [minStars, setMinStars] = useState("4.4");
  const [minReviews, setMinReviews] = useState("50");
  const [priceMin, setPriceMin] = useState("10");
  const [priceMax, setPriceMax] = useState("200");
  const [hitTarget, setHitTarget] = useState("20");
  const [maxPages, setMaxPages] = useState("5");
  const [skipSponsored, setSkipSponsored] = useState(true);
  const [status, setStatus] = useState<FindStatus | null>(null);

  const refresh = useCallback(async () => {
    try {
      const s = await api<FindStatus>("/api/find/status");
      setStatus(s);
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    }
  }, [onError]);

  const running = !!status?.running;
  const canStart = running ? false : autoMode || keyword.trim().length > 0;

  useEffect(() => {
    void refresh();
    // Poll often only while a job runs; idle polls are just noise in the API log.
    const ms = running ? 1500 : 8000;
    const id = window.setInterval(() => void refresh(), ms);
    return () => window.clearInterval(id);
  }, [refresh, running]);

  async function start() {
    onError("");
    if (!autoMode && !keyword.trim()) {
      onError("Enter a keyword or enable Auto niche mode.");
      return;
    }
    try {
      await api<FindStatus>("/api/find/start", {
        method: "POST",
        body: JSON.stringify({
          keyword,
          auto_mode: autoMode,
          min_stars: Number(minStars),
          min_reviews: Number(minReviews),
          price_min_eur: Number(priceMin),
          price_max_eur: Number(priceMax),
          skip_sponsored: skipSponsored,
          hit_target: Number(hitTarget),
          max_search_pages: Number(maxPages),
          pause_ms: 1500,
        }),
      });
      await refresh();
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    }
  }

  async function stop() {
    onError("");
    try {
      await api<FindStatus>("/api/find/stop", { method: "POST", body: "{}" });
      await refresh();
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div className="panel grid">
      <p className="muted">
        Searches amazon.de with your criteria, then runs margin Evaluate on each hit. Read-only scrape
        (not purchase automation). Goes slow on purpose (several seconds between pages) to reduce ban
        risk. CAPTCHA or empty filters stop the job early.
      </p>
      <div className="grid two">
        <label>
          Keyword (ignored if auto)
          <input
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            disabled={autoMode || running}
            placeholder="z.B. baby hocker"
          />
        </label>
        <label>
          <span>
            <input
              type="checkbox"
              checked={autoMode}
              disabled={running}
              onChange={(e) => setAutoMode(e.target.checked)}
            />{" "}
            Auto niche mode (random term + color)
          </span>
        </label>
        <label>
          Min stars
          <input value={minStars} disabled={running} onChange={(e) => setMinStars(e.target.value)} />
        </label>
        <label>
          Min reviews
          <input value={minReviews} disabled={running} onChange={(e) => setMinReviews(e.target.value)} />
        </label>
        <label>
          Price min €
          <input value={priceMin} disabled={running} onChange={(e) => setPriceMin(e.target.value)} />
        </label>
        <label>
          Price max €
          <input value={priceMax} disabled={running} onChange={(e) => setPriceMax(e.target.value)} />
        </label>
        <label>
          Hit target (margin PASS)
          <input value={hitTarget} disabled={running} onChange={(e) => setHitTarget(e.target.value)} />
        </label>
        <label>
          Max search pages
          <input value={maxPages} disabled={running} onChange={(e) => setMaxPages(e.target.value)} />
        </label>
      </div>
      <label>
        <span>
          <input
            type="checkbox"
            checked={skipSponsored}
            disabled={running}
            onChange={(e) => setSkipSponsored(e.target.checked)}
          />{" "}
          Skip sponsored
        </span>
      </label>
      <div className="actions">
        <button type="button" className="primary" disabled={!canStart} onClick={() => void start()}>
          {running ? "Running…" : "Start find"}
        </button>
        <button type="button" disabled={!running} onClick={() => void stop()}>
          Stop
        </button>
      </div>
      {!canStart && !running ? (
        <p className="muted">Type a keyword (e.g. baby hocker) or tick Auto niche mode — then Start find enables.</p>
      ) : null}
      {status ? (
        <div className="mono muted">
          keyword «{status.keyword || "—"}» · page {status.page} · examined {status.examined} · PASS{" "}
          {status.pass_count} · FAIL {status.reject_count}
          {status.error ? (
            <>
              <br />
              <span className="error">{status.error}</span>
            </>
          ) : null}
        </div>
      ) : null}
      {status && status.hits.length > 0 ? (
        <table>
          <thead>
            <tr>
              <th>ASIN</th>
              <th>Title</th>
              <th>€</th>
              <th>★</th>
              <th>Rev</th>
              <th>Result</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {status.hits
              .slice()
              .reverse()
              .map((h) => (
                <tr key={`${h.asin}-${h.candidate_id}`}>
                  <td className="mono">
                    <button
                      type="button"
                      className="linkish"
                      onClick={() => void openAmazon(h.asin).catch((e) => onError(String(e)))}
                      title="Open on Amazon"
                    >
                      {h.asin}
                    </button>
                  </td>
                  <td>{h.title || "—"}</td>
                  <td>{h.price.toFixed(2)}</td>
                  <td>{h.stars ?? "—"}</td>
                  <td>{h.reviews ?? "—"}</td>
                  <td>
                    <span className={`badge ${h.passed ? "ok" : "fail"}`}>
                      {h.passed ? "PASS" : "FAIL"}
                    </span>
                  </td>
                  <td>
                    <button
                      type="button"
                      className="linkish"
                      disabled={!h.passed}
                      onClick={() =>
                        onPrepareListing({
                          asin: h.asin,
                          title: h.title,
                          amazonTotal: h.price,
                        })
                      }
                    >
                      Prepare listing
                    </button>
                  </td>
                </tr>
              ))}
          </tbody>
        </table>
      ) : null}
      {status && status.log.length > 0 ? (
        <pre
          className="mono muted"
          style={{
            maxHeight: 180,
            overflow: "auto",
            background: "#151a17",
            padding: "0.6rem",
            margin: 0,
          }}
        >
          {status.log.slice().reverse().join("\n")}
        </pre>
      ) : null}
    </div>
  );
}

function EvaluatePanel({
  onError,
  seed,
  onSeedConsumed,
}: {
  onError: (msg: string) => void;
  seed: ListingSeed | null;
  onSeedConsumed: () => void;
}) {
  const [asinOrUrl, setAsinOrUrl] = useState("");
  const [title, setTitle] = useState("");
  const [amazonTotal, setAmazonTotal] = useState("20");
  const [ebayPrice, setEbayPrice] = useState("");
  const [sellerCountry, setSellerCountry] = useState("CN");
  const [result, setResult] = useState<EvaluateResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [draftBusy, setDraftBusy] = useState(false);
  const [draft, setDraft] = useState<ListingDraft | null>(null);
  const [copied, setCopied] = useState("");
  const [ebayListing, setEbayListing] = useState<EbayListing | null>(null);
  const [ebayBusy, setEbayBusy] = useState<"stage" | "publish" | null>(null);
  const asinOnly = asinOrUrl.trim().match(/^[A-Z0-9]{10}$/i)?.[0];

  useEffect(() => {
    if (!seed) return;
    setAsinOrUrl(seed.asin);
    setTitle(seed.title);
    setAmazonTotal(String(seed.amazonTotal));
    setEbayPrice(seed.ebayPrice != null ? String(seed.ebayPrice) : "");
    setSellerCountry(seed.sellerCountry ?? "CN");
    setResult(null);
    setDraft(null);
    setEbayListing(null);
    onSeedConsumed();
  }, [seed, onSeedConsumed]);

  useEffect(() => {
    if (!asinOnly) return;
    void (async () => {
      try {
        const listing = await api<EbayListing>(`/api/ebay/listings/${asinOnly}`);
        setEbayListing(listing);
      } catch {
        setEbayListing(null);
      }
      try {
        const existing = await api<{ draft: ListingDraft }>(`/api/listing/${asinOnly}`);
        if (existing.draft?.title) {
          setDraft(existing.draft);
        }
      } catch {
        /* no draft yet */
      }
    })();
  }, [asinOnly]);

  useEffect(() => {
    if (!copied) return;
    const t = window.setTimeout(() => setCopied(""), 1500);
    return () => window.clearTimeout(t);
  }, [copied]);

  async function runEvaluate() {
    onError("");
    setBusy(true);
    try {
      const total = Number(amazonTotal);
      const body: Record<string, unknown> = {
        asin_or_url: asinOrUrl,
        offer: {
          title: title || "Manual offer",
          amazon_total: total,
          in_stock: true,
          seller_country: sellerCountry || null,
          sold_by_amazon: false,
          asin: asinOrUrl,
          url: asinOrUrl ? amazonUrl(asinOrUrl.replace(/.*dp\//i, "").slice(0, 10)) : "",
        },
        save: true,
      };
      if (ebayPrice.trim()) {
        body.ebay_price = Number(ebayPrice);
      }
      const res = await api<EvaluateResult>("/api/evaluate", {
        method: "POST",
        body: JSON.stringify(body),
      });
      setResult(res);
      if (!ebayPrice.trim()) {
        setEbayPrice(String(res.suggested_ebay_price));
      }
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function generateDraft() {
    onError("");
    if (!asinOnly) {
      onError("ASIN required for listing draft");
      return;
    }
    setDraftBusy(true);
    try {
      const res = await api<{ draft: ListingDraft }>("/api/listing/generate", {
        method: "POST",
        body: JSON.stringify({
          asin: asinOnly,
          title,
          amazon_total: Number(amazonTotal),
          ebay_price: Number(ebayPrice || result?.ebay_price || 0),
          refresh_images: true,
        }),
      });
      setDraft(res.draft);
      try {
        setEbayListing(await api<EbayListing>(`/api/ebay/listings/${asinOnly}`));
      } catch {
        /* ignore */
      }
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setDraftBusy(false);
    }
  }

  async function copyText(label: string, text: string) {
    try {
      await navigator.clipboard.writeText(text);
      onError("");
      setCopied(label);
    } catch {
      onError(`Could not copy ${label}`);
    }
  }

  async function sendUnpublished() {
    if (!asinOnly || !draft) return;
    onError("");
    setEbayBusy("stage");
    try {
      const res = await api<EbayListing>(`/api/ebay/listings/${asinOnly}/stage`, {
        method: "POST",
        body: JSON.stringify({
          title: draft.title,
          subtitle: draft.subtitle,
          description_html: draft.description_html,
          bullet_points: draft.bullet_points,
        }),
      });
      setEbayListing(res);
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setEbayBusy(null);
    }
  }

  async function publishListing() {
    if (!asinOnly) return;
    onError("");
    setEbayBusy("publish");
    try {
      const res = await api<EbayListing>(`/api/ebay/listings/${asinOnly}/publish`, {
        method: "POST",
        body: "{}",
      });
      setEbayListing(res);
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setEbayBusy(null);
    }
  }

  return (
    <div className="panel grid">
      <p className="muted">
        1) Set eBay price & analyze margin. 2) Generate listing draft. 3) Send unpublished offer to
        eBay (sandbox while EBAY_ENV=sandbox). 4) Publish only when you click Publish — never
        automatic.
      </p>
      <div className="grid two">
        <label>
          Amazon URL / ASIN
          <input value={asinOrUrl} onChange={(e) => setAsinOrUrl(e.target.value)} placeholder="B0…" />
        </label>
        <label>
          Amazon title (source only)
          <input value={title} onChange={(e) => setTitle(e.target.value)} />
        </label>
        <label>
          Amazon total €
          <input value={amazonTotal} onChange={(e) => setAmazonTotal(e.target.value)} />
        </label>
        <label>
          eBay list price € (blank = suggest)
          <input value={ebayPrice} onChange={(e) => setEbayPrice(e.target.value)} />
        </label>
        <label>
          Seller country
          <input value={sellerCountry} onChange={(e) => setSellerCountry(e.target.value)} />
        </label>
      </div>
      <div className="actions">
        <button type="button" className="primary" disabled={busy} onClick={() => void runEvaluate()}>
          {busy ? "Working…" : "Analyze / refresh margin"}
        </button>
        {asinOnly ? (
          <button
            type="button"
            onClick={() => void openAmazon(asinOnly).catch((e) => onError(String(e)))}
          >
            Open on Amazon
          </button>
        ) : null}
        {asinOnly ? (
          <button
            type="button"
            disabled={busy}
            onClick={() => {
              void (async () => {
                onError("");
                setBusy(true);
                try {
                  const refreshed = await api<{
                    offer: {
                      title: string;
                      amazon_total: number;
                      stars?: number | null;
                      note?: string;
                    };
                    evaluate: { suggested_ebay_price: number };
                  }>("/api/amazon/refresh", {
                    method: "POST",
                    body: JSON.stringify({ asin: asinOnly }),
                  });
                  setTitle(refreshed.offer.title || title);
                  setAmazonTotal(String(refreshed.offer.amazon_total));
                  setEbayPrice(String(refreshed.evaluate.suggested_ebay_price));
                  if (refreshed.offer.note) {
                    onError(refreshed.offer.note);
                  }
                } catch (e) {
                  onError(e instanceof Error ? e.message : String(e));
                } finally {
                  setBusy(false);
                }
              })();
            }}
          >
            Refresh price from Amazon
          </button>
        ) : null}
        <button
          type="button"
          className="primary"
          disabled={draftBusy || !asinOnly || !ebayPrice}
          onClick={() => void generateDraft()}
        >
          {draftBusy ? "Generating on sparky2…" : "Generate listing draft"}
        </button>
        {copied ? <span className="muted">Copied {copied}</span> : null}
      </div>

      {result ? (
        <div className="grid" style={{ marginTop: "1rem" }}>
          <div>
            <span className={`badge ${result.passed ? "ok" : "fail"}`}>
              {result.passed ? "PASS" : "FAIL"}
            </span>{" "}
            <span className="mono">
              {result.asin} · candidate #{result.candidate_id ?? "—"} · {result.status}
            </span>
          </div>
          <div className="mono">
            Amazon €{result.offer.amazon_total.toFixed(2)} → eBay €{result.ebay_price.toFixed(2)}
            <br />
            Fees €{result.margin.ebay_fees.toFixed(2)} · Net profit €{result.margin.net_profit.toFixed(2)} (
            {(result.margin.margin_pct * 100).toFixed(1)}%)
          </div>
        </div>
      ) : null}

      {draft ? (
        <div className="panel grid" style={{ marginTop: "1rem" }}>
          <h3 style={{ margin: 0 }}>eBay draft (unique copy)</h3>
          <p className="muted">
            Model {draft.model || "—"}. Text is rewritten; Amazon images are downloaded locally and
            planned for reuse — not a mirror of the Amazon page.
          </p>
          <div className="actions">
            {draft.artifacts?.html_api ? (
              <a href={draft.artifacts.html_api} target="_blank" rel="noreferrer">
                Open saved draft page
              </a>
            ) : null}
            {draft.artifacts?.json_api ? (
              <a href={draft.artifacts.json_api} target="_blank" rel="noreferrer">
                Open draft JSON
              </a>
            ) : null}
            {asinOnly ? (
              <button
                type="button"
                onClick={() => {
                  void (async () => {
                    try {
                      const res = await api<{ url: string }>(
                        `/api/products/${asinOnly}/open-draft`,
                        { method: "POST", body: "{}" }
                      );
                      setCopied(`browser (${res.url})`);
                    } catch (e) {
                      onError(e instanceof Error ? e.message : String(e));
                    }
                  })();
                }}
              >
                Open draft in browser
              </button>
            ) : null}
          </div>
          <div className="actions">
            <button
              type="button"
              className="primary"
              disabled={ebayBusy !== null || !asinOnly}
              onClick={() => void sendUnpublished()}
            >
              {ebayBusy === "stage" ? "Sending to eBay…" : "Send unpublished offer to eBay"}
            </button>
            <button
              type="button"
              disabled={ebayBusy !== null || ebayListing?.status !== "unpublished"}
              onClick={() => void publishListing()}
            >
              {ebayBusy === "publish" ? "Publishing…" : "Publish on eBay"}
            </button>
            {ebayListing?.seller_hub_url ? (
              <button
                type="button"
                onClick={() =>
                  void openExternal(ebayListing.seller_hub_url || "").catch((e) =>
                    onError(String(e))
                  )
                }
              >
                {ebayListing.env === "sandbox" ? "Open sandbox My eBay" : "Open Seller Hub"}
              </button>
            ) : null}
            {ebayListing?.item_url ? (
              <button
                type="button"
                onClick={() =>
                  void openExternal(ebayListing.item_url || "").catch((e) => onError(String(e)))
                }
              >
                Open live item
              </button>
            ) : null}
          </div>
          {ebayListing && ebayListing.status && ebayListing.status !== "none" ? (
            <p className="muted">
              eBay {ebayListing.env || ""}: <span className="mono">{ebayListing.status}</span>
              {ebayListing.category_name ? ` · ${ebayListing.category_name}` : ""}
              {ebayListing.offer_id ? ` · offer ${ebayListing.offer_id}` : ""}
              {ebayListing.listing_id ? ` · item ${ebayListing.listing_id}` : ""}
              {ebayListing.status === "unpublished"
                ? ". Not visible on eBay yet — click Publish on eBay. Sandbox My eBay → Active is unreliable; after publish use Open live item."
                : ""}
            </p>
          ) : (
            <p className="muted">
              Send creates an unpublished offer on the connected eBay account (sandbox by default).
              Publish is a second click — it does not run by itself.
            </p>
          )}
          {(draft.media?.local_images || []).length > 0 ? (
            <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem" }}>
              {(draft.media?.local_images || []).map((img) =>
                img.api_path ? (
                  <img
                    key={img.api_path}
                    src={img.api_path}
                    alt=""
                    style={{
                      width: 72,
                      height: 72,
                      objectFit: "cover",
                      borderRadius: 4,
                      border: "1px solid var(--border, #333)",
                    }}
                  />
                ) : null
              )}
            </div>
          ) : (
            <p className="muted">No local images stored yet (download may have failed).</p>
          )}
          {(draft.media?.download_errors || []).length > 0 ? (
            <p className="muted">
              Image download: {(draft.media?.local_images || []).length} ok,{" "}
              {(draft.media?.download_errors || []).length} failed.{" "}
              {(draft.media?.download_errors || [])[0]}
            </p>
          ) : null}
          <label>
            Title
            <textarea
              rows={2}
              value={draft.title || ""}
              onChange={(e) => setDraft({ ...draft, title: e.target.value })}
            />
          </label>
          <div className="actions">
            <button type="button" onClick={() => void copyText("title", draft.title || "")}>
              Copy title
            </button>
          </div>
          <label>
            Subtitle
            <input
              value={draft.subtitle || ""}
              onChange={(e) => setDraft({ ...draft, subtitle: e.target.value })}
            />
          </label>
          <label>
            Bullets
            <textarea
              rows={5}
              value={(draft.bullet_points || []).join("\n")}
              onChange={(e) =>
                setDraft({
                  ...draft,
                  bullet_points: e.target.value.split("\n").filter((x) => x.trim()),
                })
              }
            />
          </label>
          <div className="actions">
            <button
              type="button"
              onClick={() => void copyText("bullets", (draft.bullet_points || []).join("\n"))}
            >
              Copy bullets
            </button>
          </div>
          <label>
            Description HTML
            <textarea
              rows={10}
              value={draft.description_html || ""}
              onChange={(e) => setDraft({ ...draft, description_html: e.target.value })}
            />
          </label>
          <div className="actions">
            <button
              type="button"
              onClick={() => void copyText("description", draft.description_html || "")}
            >
              Copy description HTML
            </button>
          </div>
          {draft.image_plan ? (
            <div className="muted">
              <div>Image strategy: {draft.image_plan.strategy || "—"}</div>
              <div className="mono" style={{ marginTop: "0.4rem" }}>
                Order: {(draft.image_plan.ordered_urls || []).length} urls · skip{" "}
                {(draft.image_plan.skip_urls || []).length}
              </div>
              {(draft.image_plan.ordered_urls || []).slice(0, 4).map((u) => (
                <div key={u} className="mono" style={{ fontSize: "0.75rem", wordBreak: "break-all" }}>
                  {u}
                </div>
              ))}
              <div className="actions" style={{ marginTop: "0.5rem" }}>
                <button
                  type="button"
                  onClick={() =>
                    void copyText(
                      "image urls",
                      (draft.image_plan?.ordered_urls || []).join("\n")
                    )
                  }
                >
                  Copy image URLs (recommended order)
                </button>
              </div>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function ebayOfferLabel(r: Candidate): string {
  const status = r.ebay_listing?.status;
  if (status && status !== "none") {
    return status;
  }
  if (r.listing_draft) {
    return "draft";
  }
  return "—";
}

function formatTs(iso: string): string {
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString();
  } catch {
    return iso;
  }
}

function DraftsPanel({
  onError,
  onPrepareListing,
}: {
  onError: (msg: string) => void;
  onPrepareListing: (seed: ListingSeed) => void;
}) {
  const [rows, setRows] = useState<Candidate[]>([]);
  const [filter, setFilter] = useState<"ready" | "rejected" | "all">("ready");
  const [pruneMsg, setPruneMsg] = useState("");
  const [busyAsin, setBusyAsin] = useState<string | null>(null);
  const [repriceBusy, setRepriceBusy] = useState(false);
  const [repriceMsg, setRepriceMsg] = useState("");
  const [enrichBusy, setEnrichBusy] = useState(false);
  const [enrichMsg, setEnrichMsg] = useState("");
  const enrichPollRef = useRef<number | null>(null);

    const load = useCallback(async () => {
    const q = filter === "all" ? "" : filter === "ready" ? "?status=pipeline" : `?status=${filter}`;
    setRows(await api<Candidate[]>(`/api/candidates${q}`));
  }, [filter]);

  useEffect(() => {
    void (async () => {
      try {
        await load();
      } catch (e) {
        onError(e instanceof Error ? e.message : String(e));
      }
    })();
  }, [load, onError]);

  useEffect(() => {
    return () => {
      if (enrichPollRef.current != null) {
        window.clearInterval(enrichPollRef.current);
      }
    };
  }, []);

  type EnrichStatus = {
    running: boolean;
    targeted: number;
    done: number;
    updated: number;
    index: number;
    current_asin: string | null;
    phase: string;
    error: string | null;
    errors: string[];
  };

  function formatEnrichStatus(s: EnrichStatus): string {
    const total = s.targeted || 0;
    const at = s.index || s.done || 0;
    if (s.running) {
      const asin = s.current_asin ? ` · ${s.current_asin}` : "";
      return total > 0 ? `Enriching ${at}/${total}${asin}` : "Enriching stars…";
    }
    if (s.phase === "stopped") {
      return `Stopped at ${s.updated}/${total}`;
    }
    if (total === 0) {
      return "Nothing missing stars in this filter";
    }
    return (
      `Enriched ${s.updated}/${total} from Amazon PDP` +
      (s.errors.length ? ` (${s.errors.length} errors)` : "")
    );
  }

  async function pollEnrichOnce(): Promise<boolean> {
    const s = await api<EnrichStatus>("/api/candidates/enrich-missing/status");
    setEnrichBusy(s.running);
    setEnrichMsg(formatEnrichStatus(s));
    if (s.error) onError(s.error);
    await load();
    return s.running;
  }

  async function enrichMissing() {
    onError("");
    setEnrichMsg("Starting enrich…");
    setEnrichBusy(true);
    try {
      const params = new URLSearchParams({ limit: "20" });
      if (filter !== "all") params.set("status", filter);
      await api(`/api/candidates/enrich-missing/start?${params}`, {
        method: "POST",
        body: "{}",
      });
      if (enrichPollRef.current != null) {
        window.clearInterval(enrichPollRef.current);
      }
      const tick = () => {
        void (async () => {
          try {
            const still = await pollEnrichOnce();
            if (!still && enrichPollRef.current != null) {
              window.clearInterval(enrichPollRef.current);
              enrichPollRef.current = null;
            }
          } catch (e) {
            onError(e instanceof Error ? e.message : String(e));
            setEnrichBusy(false);
            if (enrichPollRef.current != null) {
              window.clearInterval(enrichPollRef.current);
              enrichPollRef.current = null;
            }
          }
        })();
      };
      tick();
      enrichPollRef.current = window.setInterval(tick, 1500);
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
      setEnrichBusy(false);
    }
  }

  async function stopEnrich() {
    try {
      await api("/api/candidates/enrich-missing/stop", { method: "POST", body: "{}" });
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    }
  }

  async function prune() {
    onError("");
    setPruneMsg("");
    try {
      const res = await api<{ deleted: number; older_than_days: number }>(
        "/api/candidates/prune-rejected?days=7",
        { method: "POST", body: "{}" }
      );
      setPruneMsg(`Deleted ${res.deleted} rejected older than ${res.older_than_days}d`);
      await load();
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    }
  }

  async function reprice() {
    onError("");
    setRepriceMsg("");
    setRepriceBusy(true);
    try {
      const q = filter === "all" ? "" : `?status=${filter}`;
      const res = await api<{
        updated: number;
        ready: number;
        rejected: number;
        min_margin_pct: number;
      }>(`/api/candidates/reprice${q}`, { method: "POST", body: "{}" });
      setRepriceMsg(
        `Repriced ${res.updated} (ready ${res.ready}, rejected ${res.rejected}) at ${(res.min_margin_pct * 100).toFixed(0)}% min margin`
      );
      await load();
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setRepriceBusy(false);
    }
  }

  async function prepareWithRefresh(r: Candidate) {
    onError("");
    setBusyAsin(r.asin);
    try {
      const refreshed = await api<{
        offer: {
          title: string;
          amazon_total: number;
          stars?: number | null;
          reviews?: number | null;
          note?: string;
        };
        evaluate: { ebay_price: number; suggested_ebay_price: number };
      }>("/api/amazon/refresh", {
        method: "POST",
        body: JSON.stringify({ asin: r.asin }),
      });
      onPrepareListing({
        asin: r.asin,
        title: refreshed.offer.title || r.title,
        amazonTotal: refreshed.offer.amazon_total,
        ebayPrice: refreshed.evaluate.suggested_ebay_price,
      });
      await load();
    } catch (e) {
      onError(
        (e instanceof Error ? e.message : String(e)) +
          " — opening Evaluate with stored SERP price instead."
      );
      onPrepareListing({
        asin: r.asin,
        title: r.title,
        amazonTotal: r.amazon_total,
        ebayPrice: r.ebay_price,
      });
    } finally {
      setBusyAsin(null);
    }
  }

  return (
    <div className="panel grid">
      <p className="muted">
        Find stores search-page prices (can be wrong for multi-variant ASINs). Stars/reviews often
        missing until you “Fill missing stars” or “Prepare listing” (both hit the product page).
      </p>
      <div className="actions">
        {(
          [
            ["ready", "Ready"],
            ["rejected", "Rejected"],
            ["all", "All"],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            className={filter === id ? "primary" : ""}
            onClick={() => setFilter(id)}
          >
            {label}
          </button>
        ))}
        <button type="button" onClick={() => void prune()}>
          Prune old rejected
        </button>
        <button type="button" className="primary" disabled={repriceBusy} onClick={() => void reprice()}>
          {repriceBusy ? "Repricing…" : "Recalculate eBay prices"}
        </button>
        <button type="button" disabled={enrichBusy} onClick={() => void enrichMissing()}>
          {enrichBusy ? "Enriching…" : "Fill missing stars"}
        </button>
        {enrichBusy ? (
          <button type="button" onClick={() => void stopEnrich()}>
            Stop enrich
          </button>
        ) : null}
        {pruneMsg ? <span className="muted">{pruneMsg}</span> : null}
        {repriceMsg ? <span className="muted">{repriceMsg}</span> : null}
        {enrichMsg ? <span className="muted">{enrichMsg}</span> : null}
      </div>
      <table>
        <thead>
          <tr>
            <th>ASIN</th>
            <th>Title</th>
            <th>★</th>
            <th>Rev</th>
            <th>Amazon</th>
            <th>eBay</th>
            <th>Src</th>
            <th>Updated</th>
            <th>eBay offer</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}>
              <td className="mono">
                <button
                  type="button"
                  className="linkish"
                  onClick={() => void openAmazon(r.asin).catch((e) => onError(String(e)))}
                >
                  {r.asin}
                </button>
              </td>
              <td>{r.title || "—"}</td>
              <td>{r.offer?.stars ?? "—"}</td>
              <td>{r.offer?.reviews ?? "—"}</td>
              <td>€{r.amazon_total.toFixed(2)}</td>
              <td>€{r.ebay_price.toFixed(2)}</td>
              <td className="mono">{r.offer?.price_source || "serp"}</td>
              <td className="mono">{formatTs(r.updated_at)}</td>
              <td className="mono">{ebayOfferLabel(r)}</td>
              <td>
                <button
                  type="button"
                  className="linkish"
                  disabled={busyAsin === r.asin}
                  onClick={() => void prepareWithRefresh(r)}
                >
                  {busyAsin === r.asin ? "Refreshing…" : "Prepare listing"}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length === 0 ? <p className="muted">No candidates in this filter.</p> : null}
    </div>
  );
}

function SettingsPanel({
  onError,
  health,
  refreshHealth,
}: {
  onError: (msg: string) => void;
  health: Health | null;
  refreshHealth: () => Promise<Health | null>;
}) {
  const [margin, setMargin] = useState<MarginSettings | null>(null);
  const [shop, setShop] = useState<ListingShopSettings | null>(null);
  const [saved, setSaved] = useState(false);
  const [waitingOauth, setWaitingOauth] = useState(false);

  useEffect(() => {
    void (async () => {
      try {
        const s = await api<{ margin: MarginSettings; listing_shop: ListingShopSettings }>(
          "/api/settings"
        );
        setMargin(s.margin);
        setShop(s.listing_shop);
      } catch (e) {
        onError(e instanceof Error ? e.message : String(e));
      }
    })();
  }, [onError]);

  async function save() {
    if (!margin || !shop) return;
    onError("");
    setSaved(false);
    try {
      const s = await api<{ margin: MarginSettings; listing_shop: ListingShopSettings }>(
        "/api/settings",
        {
          method: "PUT",
          body: JSON.stringify({ margin, listing_shop: shop }),
        }
      );
      setMargin(s.margin);
      setShop(s.listing_shop);
      setSaved(true);
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    }
  }

  if (!margin || !shop) {
    return <div className="panel muted">Loading settings…</div>;
  }

  let oauthStatus = "not connected";
  if (health?.ebay?.oauth_connected) {
    oauthStatus = "connected";
  } else if (waitingOauth) {
    oauthStatus = "waiting for browser…";
  }

  return (
    <div className="panel grid">
      <p className="muted">
        Automation masters live in <span className="mono">.env</span> (read-only here): Amazon{" "}
        {health?.automation.amazon_enabled ? "ON" : "off"}, eBay{" "}
        {health?.automation.ebay_enabled ? "ON" : "off"}. Ollama: {health?.ollama_base_url ?? "—"}
      </p>
      <h3 style={{ margin: "0.5rem 0 0" }}>eBay API</h3>
      <p className="muted">
        Environment: <span className="mono">{health?.ebay?.env ?? "—"}</span>
        {" · "}
        keys {health?.ebay?.app_id_set && health?.ebay?.cert_id_set ? "present" : "missing"}
        {health?.ebay?.app_id_hint ? ` (${health.ebay.app_id_hint})` : ""}
        {" · "}
        RuName {health?.ebay?.runame_set ? "set" : "not set"}
        {" · "}
        OAuth {oauthStatus}
        {" · "}
        auto-publish {health?.ebay?.auto_publish ? "ON" : "off"}
        {" · "}
        send-to-eBay {health?.ebay?.sell_allowed ? "allowed" : health?.ebay?.sell_block_reason || "blocked"}
      </p>
      <div className="actions">
        <button
          type="button"
          className="primary"
          disabled={waitingOauth}
          onClick={() => {
            void (async () => {
              try {
                await api("/api/ebay/oauth/start", { method: "POST", body: "{}" });
                setWaitingOauth(true);
                const deadline = Date.now() + 180_000;
                while (Date.now() < deadline) {
                  await new Promise((r) => window.setTimeout(r, 1500));
                  const h = await refreshHealth();
                  if (h?.ebay?.oauth_connected) {
                    break;
                  }
                }
              } catch (e) {
                onError(e instanceof Error ? e.message : String(e));
              } finally {
                setWaitingOauth(false);
              }
            })();
          }}
        >
          {health?.ebay?.oauth_connected ? "Reconnect eBay (Sandbox)" : "Connect eBay (Sandbox)"}
        </button>
      </div>
      <p className="muted">
        Auth accepted URL:{" "}
        <span className="mono">https://127.0.0.1:8770/api/ebay/oauth/callback</span>
        . After eBay redirects, Chrome will warn about the local self-signed certificate — Advanced →
        Proceed (the <span className="mono">code=</span> in the URL must stay).
      </p>
      {!health?.ebay?.runame_set ? (
        <p className="muted">
          Put the RuName in <span className="mono">EBAY_SANDBOX_RUNAME</span>, then restart.
        </p>
      ) : null}
      <h3 style={{ margin: "0.5rem 0 0" }}>Margin</h3>
      <div className="grid two">
        {(
          [
            ["ebay_fee_pct", "eBay fee %"],
            ["ebay_fee_fixed", "eBay fixed €"],
            ["buffer_eur", "Buffer €"],
            ["min_margin_eur", "Min margin €"],
            ["min_margin_pct", "Min margin % (0–1)"],
            ["max_delivery_days", "Max delivery days"],
          ] as const
        ).map(([key, label]) => (
          <label key={key}>
            {label}
            <input
              value={String(margin[key])}
              onChange={(e) =>
                setMargin({ ...margin, [key]: Number(e.target.value) })
              }
            />
          </label>
        ))}
      </div>
      <label>
        <span>
          <input
            type="checkbox"
            checked={margin.skip_sold_by_amazon}
            onChange={(e) => setMargin({ ...margin, skip_sold_by_amazon: e.target.checked })}
          />{" "}
          Skip sold-by-Amazon
        </span>
      </label>
      <label>
        <span>
          <input
            type="checkbox"
            checked={margin.reject_dach_sellers}
            onChange={(e) => setMargin({ ...margin, reject_dach_sellers: e.target.checked })}
          />{" "}
          Reject DACH sellers
        </span>
      </label>

      <h3 style={{ margin: "1rem 0 0" }}>Listing description template</h3>
      <p className="muted">
        Static shop sections (Versand, Rückgabe, Zahlung, Feedback, Kontakt) are appended to every
        generated draft. LLM only writes the product block.
      </p>
      <div className="grid two">
        <label>
          Shop name
          <input
            value={shop.shop_name}
            onChange={(e) => setShop({ ...shop, shop_name: e.target.value })}
          />
        </label>
        <label>
          Accent color
          <input
            value={shop.accent_color}
            onChange={(e) => setShop({ ...shop, accent_color: e.target.value })}
          />
        </label>
      </div>
      {(
        [
          ["shipping_html", "Versand HTML"],
          ["returns_html", "Rückgabe HTML"],
          ["payment_html", "Zahlung HTML"],
          ["feedback_html", "Feedback HTML"],
          ["contact_html", "Kontakt HTML"],
          ["photo_disclaimer_html", "Foto-Hinweis HTML"],
        ] as const
      ).map(([key, label]) => (
        <label key={key}>
          {label}
          <textarea
            rows={4}
            value={shop[key]}
            onChange={(e) => setShop({ ...shop, [key]: e.target.value })}
          />
        </label>
      ))}

      <div className="actions">
        <button type="button" className="primary" onClick={() => void save()}>
          Save settings
        </button>
        {saved ? <span className="muted">Saved.</span> : null}
      </div>
    </div>
  );
}
