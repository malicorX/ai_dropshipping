import { useCallback, useEffect, useRef, useState } from "react";

import {
  LEGACY_LIVE_DISABLED_REASON,
  legacyListingDisabled,
  liveBannerVisible,
  withPlanNonce,
} from "./liveUi";
import {
  previewFileToLoad,
  rowDurationSeconds,
  runRowsMatchSelectedFile,
  uploadDurationStats,
} from "./uploadDuration";

type Tab = "find" | "queue" | "list" | "upload" | "prepared" | "settings";

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
    production_ready?: boolean;
    sandbox_oauth_connected?: boolean;
    production_oauth_connected?: boolean;
    sandbox_gaps?: string[];
    production_gaps?: string[];
    live_upload_enabled?: boolean;
    live_max_per_run?: number;
    live_upload_missing?: string[];
    live_upload_ready?: boolean;
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
    variation_label?: string;
    parent_asin?: string;
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

type UploadRow = {
  line_no: number;
  line: string;
  asin: string;
  state: string;
  reason: string;
  offer_id: string;
  listing_id: string;
  item_url: string;
  started_at: string;
  finished_at: string;
  duration_sec: number | null;
  attempts: number;
};

type UploadFileEntry = {
  name: string;
  size: number;
  modified: string;
  lines: number;
};

type UploadFiles = {
  dir: string;
  default: string;
  files: UploadFileEntry[];
};

type UploadPreview = {
  target_env: string;
  live_disabled: boolean;
  live_enabled?: boolean;
  live_missing?: string[];
  live_cap?: number;
  path: string;
  file: string;
  rows: UploadRow[];
};

type LivePlanItem = {
  asin: string;
  title: string;
  price: number | null;
};

type LivePlan = {
  mode: string;
  env: string;
  n: number;
  batch_hash: string;
  nonce: string;
  cap: number;
  total: number;
  items: LivePlanItem[];
  live_enabled: boolean;
  live_missing: string[];
};

type UploadStatus = {
  run_id: string;
  target_env: string;
  started_at: string;
  running: boolean;
  stop_requested: boolean;
  phase: string;
  mode: string;
  error: string;
  file: string;
  retry_pass: number;
  live?: boolean;
  batch_hash?: string;
  live_cap?: number;
  planned?: number;
  rows: UploadRow[];
  counters: Record<string, number>;
};

type PreparedItem = {
  asin: string;
  title: string;
  ebay_price: number;
  amazon_total: number;
  margin: {
    margin_pct?: number;
    passed?: boolean;
    fail_reasons?: string[];
  };
  prepared_at: string;
  ebay_status: string;
  offer_id: string;
  age_days: number;
};

type PreparedOverview = {
  target_env: string;
  live_disabled: boolean;
  live_enabled?: boolean;
  live_missing?: string[];
  live_cap?: number;
  items: PreparedItem[];
};

const UPLOAD_STATE_LABELS: Record<string, string> = {
  queued: "queued",
  fetching: "fetching",
  evaluated: "evaluated",
  drafted: "drafted",
  prepared: "prepared",
  staged: "staged",
  published: "published",
  skipped_existing: "haben wir schon",
  already_listed: "haben wir schon",
  not_prepared: "not prepared",
  not_found: "not found",
  rejected: "rejected",
  error: "error",
  duplicate_in_file: "duplicate in file",
};

function uploadStateLabel(state: string): string {
  return UPLOAD_STATE_LABELS[state] ?? state.replace(/_/g, " ");
}

function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) {
    return "—";
  }
  const total = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  return `${minutes}:${String(rest).padStart(2, "0")}`;
}

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
    setTab("list");
    setError("");
  }, []);

  const refreshHealth = useCallback(async (): Promise<Health | null> => {
    try {
      const h = await api<Health>("/api/health");
      setHealth(h);
      return h;
    } catch {
      setHealth(null);
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

  const ebayLive = health?.ebay?.env === "production";

  useEffect(() => {
    document.documentElement.dataset.ebayTarget = ebayLive ? "production" : "sandbox";
  }, [ebayLive]);

  return (
    <div className={ebayLive ? "app ebay-live" : "app ebay-sandbox"}>
      <header className="top">
        <h1>Dropship Desk</h1>
        <div className="health">
          {health ? (
            <>
              {`v${health.version} · API ok · `}
              <span
                className={
                  health.ebay?.env === "production" ? "ebay-target-pill live" : "ebay-target-pill"
                }
              >
                {health.ebay?.env === "production" ? "eBay LIVE" : "eBay sandbox"}
              </span>
              {health.ebay?.oauth_connected ? " · signed in" : " · not signed in"}
            </>
          ) : (
            "API unreachable"
          )}
        </div>
      </header>

      <nav className="tabs">
        {(
          [
            ["find", "Find on Amazon"],
            ["queue", "Queue"],
            ["list", "List on eBay"],
            ["upload", "Upload items"],
            ["prepared", "Prepared"],
            ["settings", "Settings"],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            className={tab === id ? "active" : ""}
            onClick={() => {
              setError("");
              setTab(id);
            }}
          >
            {label}
          </button>
        ))}
      </nav>

      {error ? <p className="error">{error}</p> : null}

      {tab === "find" && (
        <FindPanel onError={setError} onPrepareListing={prepareListing} />
      )}
      {tab === "queue" && (
        <DraftsPanel
          onError={setError}
          onPrepareListing={prepareListing}
          ebayEnv={health?.ebay?.env === "production" ? "production" : "sandbox"}
        />
      )}
      {tab === "list" && (
        <EvaluatePanel
          onError={setError}
          seed={listingSeed}
          onSeedConsumed={() => setListingSeed(null)}
          ebayEnv={health?.ebay?.env === "production" ? "production" : "sandbox"}
        />
      )}
      {tab === "settings" && (
        <SettingsPanel onError={setError} health={health} refreshHealth={refreshHealth} />
      )}
      {tab === "upload" && <UploadItemsPanel onError={setError} />}
      {tab === "prepared" && <PreparedPanel onError={setError} live={ebayLive} />}
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
    } catch {
      /* idle poll — header already shows API unreachable */
    }
  }, []);

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
        Search amazon.de. Hits that cover fees + your min margin go to Queue. Sizes/colors
        (20 kg vs 40 kg) become separate rows. Then open a row to list it on eBay. Slow on
        purpose; a CAPTCHA stops the job.
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
                      List on eBay
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
  ebayEnv,
}: {
  onError: (msg: string) => void;
  seed: ListingSeed | null;
  onSeedConsumed: () => void;
  ebayEnv: "sandbox" | "production";
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
  }, [asinOnly, ebayEnv]);

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
    if (legacyListingDisabled(ebayEnv)) {
      onError(LEGACY_LIVE_DISABLED_REASON);
      return;
    }
    if (ebayEnv === "production") {
      const ok = window.confirm(
        `Send this unpublished offer to LIVE eBay?\n\n${draft.title || asinOnly}\n\nThis is not the sandbox.`
      );
      if (!ok) return;
    }
    setEbayBusy("stage");
    try {
      const res = await api<EbayListing>(`/api/ebay/listings/${asinOnly}/stage`, {
        method: "POST",
        body: JSON.stringify({
          title: draft.title,
          subtitle: draft.subtitle,
          description_html: draft.description_html,
          bullet_points: draft.bullet_points,
          confirm_live: ebayEnv === "production",
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
    if (legacyListingDisabled(ebayEnv)) {
      onError(LEGACY_LIVE_DISABLED_REASON);
      return;
    }
    if (ebayEnv === "production") {
      const ok = window.confirm(
        `Publish this offer on LIVE eBay? Buyers will see it.\n\n${
          draft?.title || asinOnly
        }\n\nThis is not the sandbox.`
      );
      if (!ok) return;
    }
    setEbayBusy("publish");
    try {
      const res = await api<EbayListing>(`/api/ebay/listings/${asinOnly}/publish`, {
        method: "POST",
        body: JSON.stringify({ confirm_live: ebayEnv === "production" }),
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
        Open an item from Queue, or paste an ASIN. Generate unique eBay copy, send an unpublished
        offer, then Publish — never automatic. Margin was already checked in Find; this page is for
        listing, not hunting.
      </p>
      {ebayEnv === "production" ? (
        <p className="error">
          Target is live eBay. Send and Publish are disabled here —{" "}
          {LEGACY_LIVE_DISABLED_REASON} (Settings → Sandbox to use this page).
        </p>
      ) : null}
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
        <button type="button" disabled={busy} onClick={() => void runEvaluate()}>
          {busy ? "Working…" : "Recheck margin"}
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
                      asin?: string;
                      stars?: number | null;
                      note?: string;
                      variation_label?: string;
                    };
                    evaluate: { suggested_ebay_price: number; asin?: string };
                    expanded?: boolean;
                    children?: { asin: string; variation_label: string; amazon_total: number }[];
                  }>("/api/amazon/refresh", {
                    method: "POST",
                    body: JSON.stringify({ asin: asinOnly }),
                  });
                  const nextAsin = refreshed.offer.asin || refreshed.evaluate.asin;
                  if (nextAsin) {
                    setAsinOrUrl(nextAsin);
                  }
                  setTitle(refreshed.offer.title || title);
                  setAmazonTotal(String(refreshed.offer.amazon_total));
                  setEbayPrice(String(refreshed.evaluate.suggested_ebay_price));
                  if (refreshed.expanded && (refreshed.children || []).length > 1) {
                    onError(
                      `Split into ${(refreshed.children || []).length} variations (e.g. ${
                        refreshed.offer.variation_label || "child ASIN"
                      }). Each size/color is its own row in Queue.`
                    );
                  } else if (refreshed.offer.note) {
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
              disabled={
                ebayBusy !== null || !asinOnly || legacyListingDisabled(ebayEnv)
              }
              title={
                legacyListingDisabled(ebayEnv)
                  ? LEGACY_LIVE_DISABLED_REASON
                  : undefined
              }
              onClick={() => void sendUnpublished()}
            >
              {ebayBusy === "stage"
                ? ebayEnv === "production"
                  ? "Sending to live eBay…"
                  : "Sending to sandbox…"
                : ebayEnv === "production"
                  ? "Send unpublished offer to live eBay"
                  : "Send unpublished offer to sandbox"}
            </button>
            <button
              type="button"
              disabled={
                ebayBusy !== null ||
                ebayListing?.status !== "unpublished" ||
                legacyListingDisabled(ebayEnv)
              }
              title={
                legacyListingDisabled(ebayEnv)
                  ? LEGACY_LIVE_DISABLED_REASON
                  : undefined
              }
              onClick={() => void publishListing()}
            >
              {ebayBusy === "publish"
                ? "Publishing…"
                : ebayEnv === "production"
                  ? "Publish on live eBay"
                  : "Publish on sandbox"}
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
                {ebayListing.env === "sandbox" ? "Open sandbox My eBay" : "Open My eBay"}
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
                ? ebayEnv === "production"
                  ? ". Not visible on eBay yet — click Publish on live eBay. Seller Hub has no draft for this offer."
                  : ". Not visible on eBay yet — click Publish on sandbox. After publish use Open live item."
                : ""}
            </p>
          ) : (
            <p className="muted">
              Send creates an unpublished offer on the connected{" "}
              {ebayEnv === "production" ? "live" : "sandbox"} eBay account (Settings → eBay target).
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
  ebayEnv,
}: {
  onError: (msg: string) => void;
  onPrepareListing: (seed: ListingSeed) => void;
  ebayEnv: "sandbox" | "production";
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
  }, [load, onError, ebayEnv]);

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
          asin?: string;
          stars?: number | null;
          reviews?: number | null;
          note?: string;
        };
        evaluate: { ebay_price: number; suggested_ebay_price: number; asin?: string };
      }>("/api/amazon/refresh", {
        method: "POST",
        body: JSON.stringify({ asin: r.asin }),
      });
      onPrepareListing({
        asin: refreshed.offer.asin || refreshed.evaluate.asin || r.asin,
        title: refreshed.offer.title || r.title,
        amazonTotal: refreshed.offer.amazon_total,
        ebayPrice: refreshed.evaluate.suggested_ebay_price,
      });
      await load();
    } catch (e) {
      onError(
        (e instanceof Error ? e.message : String(e)) +
          " — opening List on eBay with the stored search price instead."
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
        Items that passed Find (margin + in-stock). Click List on eBay to write copy and send it.
        Refresh Amazon if a row is still a generic parent (no size/color).
      </p>
      {legacyListingDisabled(ebayEnv) ? (
        <p className="upload-warning">{LEGACY_LIVE_DISABLED_REASON}</p>
      ) : null}
      <div className="actions">
        {(
          [
            ["ready", "Ready to list"],
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
        {filter === "rejected" ? (
          <button type="button" onClick={() => void prune()}>
            Delete rejected older than 7 days
          </button>
        ) : null}
        <button type="button" className="primary" disabled={repriceBusy} onClick={() => void reprice()}>
          {repriceBusy ? "Repricing…" : "Recalculate eBay prices"}
        </button>
        <button type="button" disabled={enrichBusy} onClick={() => void enrichMissing()}>
          {enrichBusy ? "Refreshing…" : "Refresh Amazon / split sizes"}
        </button>
        {enrichBusy ? (
          <button type="button" onClick={() => void stopEnrich()}>
            Stop refresh
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
            <th>{ebayEnv === "production" ? "Live offer" : "Sandbox offer"}</th>
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
              <td>
                {r.title || "—"}
                {r.offer?.variation_label ? (
                  <div className="muted">{r.offer.variation_label}</div>
                ) : null}
              </td>
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
                  disabled={busyAsin === r.asin || legacyListingDisabled(ebayEnv)}
                  title={
                    legacyListingDisabled(ebayEnv)
                      ? LEGACY_LIVE_DISABLED_REASON
                      : undefined
                  }
                  onClick={() => void prepareWithRefresh(r)}
                >
                  {busyAsin === r.asin ? "Refreshing…" : "List on eBay"}
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

function RunProgressTable({
  rows,
  running,
  nowMs,
}: {
  rows: UploadRow[];
  running: boolean;
  nowMs: number;
}) {
  return (
    <table>
      <thead>
        <tr>
          <th>ASIN</th>
          <th>State</th>
          <th>Reason</th>
          <th>Time</th>
          <th>Offer</th>
          <th>Sandbox item</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => {
          const bad = ["error", "rejected", "not_found"].includes(row.state);
          const good = ["published", "prepared", "skipped_existing", "already_listed"].includes(
            row.state,
          );
          return (
            <tr key={row.line_no}>
              <td className="mono">{row.asin || "—"}</td>
              <td>
                <span className={bad ? "badge fail" : good ? "badge ok" : "badge"}>
                  {uploadStateLabel(row.state)}
                </span>
                {row.attempts > 1 ? (
                  <span className="muted"> {row.attempts}x</span>
                ) : null}
              </td>
              <td>{row.reason || "—"}</td>
              <td className="mono">
                {formatDuration(rowDurationSeconds(row, nowMs, running))}
              </td>
              <td className="mono">{row.offer_id || "—"}</td>
              <td>
                {row.item_url ? (
                  <a href={row.item_url} target="_blank" rel="noreferrer">
                    {row.listing_id || "open"}
                  </a>
                ) : (
                  row.listing_id || "—"
                )}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function LivePlanPanel({
  mode,
  file,
  asins,
  disabled,
  runLabel,
  onError,
  onRun,
}: {
  mode: "upload" | "publish";
  file?: string;
  asins?: string[];
  disabled?: boolean;
  runLabel?: string;
  onError: (msg: string) => void;
  onRun: (plan: LivePlan, confirm: string) => Promise<void>;
}) {
  const [plan, setPlan] = useState<LivePlan | null>(null);
  const [confirmText, setConfirmText] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  const selectionKey =
    mode === "upload" ? (file ?? "") : (asins ?? []).join(",");
  useEffect(() => {
    setPlan(null);
    setConfirmText("");
    setMsg("");
  }, [selectionKey, mode]);

  const expected = plan ? `LIVE ${plan.n}` : "";
  const overCap = !!plan && plan.n > plan.cap;
  const matches =
    !!plan && plan.live_enabled && !overCap && confirmText === expected;

  async function makePlan() {
    onError("");
    setBusy(true);
    setMsg("Planning…");
    try {
      const body =
        mode === "upload"
          ? { mode: "upload", file: file || undefined }
          : { mode: "publish", asins: asins ?? [] };
      const next = await api<LivePlan>("/api/live/plan", {
        method: "POST",
        body: JSON.stringify(body),
      });
      setPlan(next);
      setConfirmText("");
      setMsg(
        `Plan: ${next.n} item(s), total €${next.total.toFixed(2)}, cap ${next.cap}`,
      );
    } catch (e) {
      const text = e instanceof Error ? e.message : String(e);
      onError(text);
      setMsg(text);
    } finally {
      setBusy(false);
    }
  }

  async function run() {
    if (!plan || !matches) {
      return;
    }
    onError("");
    setBusy(true);
    setMsg("Starting live run…");
    try {
      await onRun(plan, confirmText);
      setMsg("Live run started.");
    } catch (e) {
      const text = e instanceof Error ? e.message : String(e);
      onError(text);
      setMsg(text);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="live-plan">
      <div className="actions">
        <button
          type="button"
          className="primary"
          disabled={!!disabled || busy}
          onClick={() => void makePlan()}
        >
          {busy && !plan ? "Planning…" : "Live: plan..."}
        </button>
        {msg ? <span className="muted">{msg}</span> : null}
      </div>
      {plan ? (
        <>
          <p className="live-plan-summary">
            LIVE <strong>{plan.n}</strong> item(s) · total €{plan.total.toFixed(2)} · cap{" "}
            {plan.cap} · {plan.mode}
          </p>
          {!plan.live_enabled ? (
            <p className="upload-warning">
              Live gate closed: {plan.live_missing.join(", ") || "unknown gate"}.
            </p>
          ) : null}
          {overCap ? (
            <p className="upload-warning">
              Batch of {plan.n} exceeds the live cap of {plan.cap}.
            </p>
          ) : null}
          <table>
            <thead>
              <tr>
                <th>ASIN</th>
                <th>Title</th>
                <th>Price</th>
              </tr>
            </thead>
            <tbody>
              {plan.items.slice(0, 6).map((item) => (
                <tr key={item.asin}>
                  <td className="mono">{item.asin}</td>
                  <td>{item.title || "—"}</td>
                  <td className="mono">
                    {item.price === null ? "—" : `€${item.price.toFixed(2)}`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {plan.items.length > 6 ? (
            <p className="muted">… {plan.items.length - 6} more item(s)</p>
          ) : null}
          <div className="actions live-confirm">
            <label>
              Type <span className="mono">{expected}</span> exactly{" "}
              <input
                value={confirmText}
                onChange={(event) => setConfirmText(event.target.value)}
                autoComplete="off"
                spellCheck={false}
                disabled={busy}
              />
            </label>
            <button
              type="button"
              className="primary"
              disabled={busy || !matches || !!disabled}
              onClick={() => void run()}
            >
              {runLabel || `LIVE: ${plan.n} item(s)`}
            </button>
          </div>
        </>
      ) : null}
    </div>
  );
}

const UPLOAD_FILE_STORAGE_KEY = "dropship.uploadFile";

function UploadItemsPanel({ onError }: { onError: (msg: string) => void }) {
  const [preview, setPreview] = useState<UploadPreview | null>(null);
  const [status, setStatus] = useState<UploadStatus | null>(null);
  const [fileList, setFileList] = useState<UploadFiles | null>(null);
  const [selectedFile, setSelectedFile] = useState<string>(() => {
    try {
      return window.localStorage.getItem(UPLOAD_FILE_STORAGE_KEY) ?? "";
    } catch {
      return "";
    }
  });
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [nowMs, setNowMs] = useState(() => Date.now());
  const previewFailed = useRef(false);

  const loadFiles = useCallback(async () => {
    try {
      setFileList(await api<UploadFiles>("/api/upload-items/files"));
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    }
  }, [onError]);

  const loadPreview = useCallback(async () => {
    const query = selectedFile
      ? `?file=${encodeURIComponent(selectedFile)}`
      : "";
    try {
      const next = await api<UploadPreview>(`/api/upload-items/preview${query}`);
      setPreview(next);
      if (previewFailed.current) {
        previewFailed.current = false;
        onError("");
      }
    } catch (e) {
      previewFailed.current = true;
      onError(e instanceof Error ? e.message : String(e));
    }
  }, [onError, selectedFile]);

  const loadStatus = useCallback(async () => {
    try {
      setStatus(await api<UploadStatus>("/api/upload-items/status"));
    } catch {
      /* header already reports an unreachable API */
    }
  }, []);

  useEffect(() => {
    void loadFiles();
  }, [loadFiles]);

  // Once the folder listing arrives, keep the remembered name when it still
  // exists; otherwise fall back to upload_items.txt (or the newest list).
  useEffect(() => {
    if (!fileList) {
      return;
    }
    const names = fileList.files.map((entry) => entry.name);
    setSelectedFile((current) =>
      current && names.includes(current) ? current : fileList.default || names[0] || "",
    );
  }, [fileList]);

  useEffect(() => {
    void loadStatus();
    const id = window.setInterval(() => {
      void loadStatus();
    }, 2000);
    return () => window.clearInterval(id);
  }, [loadStatus]);

  // Do not preview a remembered file before /files confirms it still exists:
  // a stale localStorage entry would otherwise produce a pointless 400.  Wait
  // for the listing, then the selection effect above falls back to the
  // default and this effect previews that valid name.
  useEffect(() => {
    if (previewFileToLoad(fileList, selectedFile) === null) {
      return;
    }
    void loadPreview();
  }, [fileList, selectedFile, loadPreview]);

  function chooseFile(name: string) {
    setSelectedFile(name);
    try {
      window.localStorage.setItem(UPLOAD_FILE_STORAGE_KEY, name);
    } catch {
      /* storage may be disabled; the choice still holds for this session */
    }
  }

  const anyRunning = !!status?.running;
  // A publish run belongs to the Prepared tab; this panel renders progress and
  // previews only for full and prepare runs.
  const publishRunning = anyRunning && status?.mode === "publish";
  const running = anyRunning && !publishRunning;
  const hasUploadStatus = status?.mode === "full" || status?.mode === "prepare";
  const wasRunning = useRef(false);

  // Tick once a second so the running row's Time cell advances.
  useEffect(() => {
    if (!running) {
      return;
    }
    setNowMs(Date.now());
    const id = window.setInterval(() => setNowMs(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [running]);

  // Preview loads on mount above.  Refresh it once after a run we observed
  // running has ended, so a later file-only preview sees the new listings.
  useEffect(() => {
    if (running) {
      wasRunning.current = true;
      return;
    }
    if (wasRunning.current) {
      wasRunning.current = false;
      void loadPreview();
    }
  }, [running, loadPreview]);
  const liveEnv = preview?.target_env || "sandbox";
  // When no run is active the badge must describe the current Settings
  // target, not the target_env remembered from the last run.
  const target = running ? status?.target_env || liveEnv : liveEnv;
  const production = target === "production";
  const liveReady =
    production && (!!preview?.live_enabled || (running && !!status?.live));
  const liveBlocked = production && !liveReady;
  const liveReason =
    (preview?.live_missing ?? []).join(", ") ||
    "EBAY_LIVE_UPLOAD_ENABLED is false";
  // Run rows belong to the file that was actually started.  If the selected
  // file differs (or there is no upload run at all), show the preview of the
  // selected file instead of another file's run.
  const selectedRun = runRowsMatchSelectedFile(
    hasUploadStatus,
    status?.run_id ?? "",
    status?.file ?? "",
    selectedFile,
  );
  const rows = selectedRun ? status?.rows ?? [] : preview?.rows ?? [];
  const counters = selectedRun ? status?.counters ?? {} : {};
  const durationStats = uploadDurationStats(rows, nowMs, running);

  async function start(mode: "full" | "prepare") {
    onError("");
    setMsg(mode === "prepare" ? "Preparing…" : "Starting…");
    setBusy(true);
    try {
      const next = await api<UploadStatus>("/api/upload-items/start", {
        method: "POST",
        body: JSON.stringify({ mode, file: selectedFile || undefined }),
      });
      setStatus(next);
      setMsg(`Started ${next.run_id} (${next.mode})`);
      await loadPreview();
    } catch (e) {
      const text = e instanceof Error ? e.message : String(e);
      onError(text);
      setMsg(text);
    } finally {
      setBusy(false);
    }
  }

  async function startLive(plan: LivePlan, confirm: string) {
    const next = await api<UploadStatus>("/api/upload-items/start", {
      method: "POST",
      body: JSON.stringify(
        withPlanNonce(plan, {
          mode: "full",
          file: selectedFile || undefined,
          confirm,
          batch_hash: plan.batch_hash,
        }),
      ),
    });
    setStatus(next);
    setMsg(`Started live ${next.run_id} (${next.mode})`);
    await loadPreview();
  }

  async function stop() {
    onError("");
    try {
      setStatus(
        await api<UploadStatus>("/api/upload-items/stop", { method: "POST", body: "{}" })
      );
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div className="panel grid upload-panel">
      <div className="upload-head">
        <div>
          <h2>Upload items from file</h2>
          <p className="muted">
            Reads <span className="mono">{preview?.file || "upload_items.txt"}</span> from{" "}
            <span className="mono">{fileList?.dir || "upload_items/"}</span> (one Amazon.de
            link per line) and runs every link through fetch → evaluate → draft → stage →
            publish. Sequential and reattaches after a reload.
          </p>
        </div>
        <span className={production ? "upload-target live" : "upload-target"}>
          {production
            ? liveReady
              ? "LIVE (guarded)"
              : "LIVE disabled"
            : "-> sandbox eBay"}
        </span>
      </div>
      {liveBlocked ? (
        <p className="upload-warning">
          Production live path is closed: {liveReason}. Nothing is sent to eBay until every
          gate is open. Switch to sandbox eBay in Settings to use the sandbox path.
        </p>
      ) : null}
      {liveBannerVisible(status) ? (
        <div className="live-run-banner">PRODUCTION - real listings</div>
      ) : null}
      <div className="actions upload-file-picker">
        <label htmlFor="upload-file-select">List file</label>
        <select
          id="upload-file-select"
          value={selectedFile}
          disabled={anyRunning || busy}
          onChange={(event) => chooseFile(event.target.value)}
        >
          {selectedFile &&
          !(fileList?.files ?? []).some((entry) => entry.name === selectedFile) ? (
            <option value={selectedFile}>{selectedFile}</option>
          ) : null}
          {(fileList?.files ?? []).map((entry) => (
            <option key={entry.name} value={entry.name}>
              {entry.name} · {entry.lines} lines
            </option>
          ))}
        </select>
        {fileList && fileList.files.length === 0 ? (
          <span className="muted">No .txt files in {fileList.dir}</span>
        ) : null}
      </div>
      <div className="actions">
        <button type="button" onClick={() => void loadPreview()}>
          Preview
        </button>
        {!production ? (
          <button
            type="button"
            className="primary"
            disabled={anyRunning || busy}
            onClick={() => void start("full")}
          >
            {running && status?.mode !== "prepare" ? "Uploading…" : "Start upload from file"}
          </button>
        ) : liveReady ? (
          <LivePlanPanel
            mode="upload"
            file={selectedFile || undefined}
            disabled={anyRunning || busy}
            runLabel="LIVE: upload this file"
            onError={onError}
            onRun={startLive}
          />
        ) : null}
        <button
          type="button"
          disabled={anyRunning || liveBlocked || busy}
          onClick={() => void start("prepare")}
        >
          {running && status?.mode === "prepare" ? "Preparing…" : "Only prepare (no eBay)"}
        </button>
        {anyRunning ? (
          <button type="button" onClick={() => void stop()}>
            Stop
          </button>
        ) : null}
        {msg ? <span className="muted">{msg}</span> : null}
      </div>
      <p className="hint">
        One click starts the run at once. Items already listed are marked 'haben wir schon' and
        not uploaded again. "Only prepare" fetches, evaluates and drafts without any eBay call —
        publish later from the Prepared tab.
      </p>
      <p className="muted">
        {publishRunning
          ? "Publish run in progress, see the Prepared tab."
          : running
            ? `Run ${status?.run_id || "…"} · ${status?.phase || "starting"} · ${status?.file || "…"}`
            : hasUploadStatus && status?.run_id
              ? `Last run ${status.run_id} · ${status.phase} · ${status.file || "…"}`
              : status?.mode === "publish"
                ? "Last run was a publish run, see the Prepared tab."
                : "No run yet."}
        {counters.total
          ? ` · ${counters.done ?? 0}/${counters.total} done · ${counters.published ?? 0} published`
          : ""}
        {hasUploadStatus && status?.error ? ` · ${status.error}` : ""}
      </p>
      {durationStats.processed > 0 ? (
        <p className="muted upload-duration-summary">
          total {formatDuration(durationStats.totalSec)}, average per processed item{" "}
          {formatDuration(durationStats.averageSec)}
        </p>
      ) : null}
      <RunProgressTable rows={rows} running={running} nowMs={nowMs} />
      {rows.length === 0 ? <p className="muted">No rows in the upload file.</p> : null}
    </div>
  );
}

function formatAgeDays(days: number): string {
  if (!Number.isFinite(days)) {
    return "—";
  }
  if (days < 1) {
    return "<1 d";
  }
  return `${Math.floor(days)} d`;
}

function formatMarginPct(value: number | undefined): string {
  if (value === undefined || !Number.isFinite(value)) {
    return "—";
  }
  return `${(value * 100).toFixed(0)}%`;
}

function preparedStatusLabel(status: string): string {
  if (status === "unpublished") {
    return "staged (offer ready)";
  }
  if (status === "none") {
    return "not on eBay";
  }
  return status || "—";
}

function PreparedPanel({
  onError,
  live,
}: {
  onError: (msg: string) => void;
  live: boolean;
}) {
  const [overview, setOverview] = useState<PreparedOverview | null>(null);
  const [status, setStatus] = useState<UploadStatus | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [nowMs, setNowMs] = useState(() => Date.now());

  const load = useCallback(async () => {
    try {
      const next = await api<PreparedOverview>("/api/prepared");
      setOverview(next);
      const stillThere = new Set(next.items.map((item) => item.asin));
      setSelected((prev) => prev.filter((asin) => stillThere.has(asin)));
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    }
  }, [onError]);

  const loadStatus = useCallback(async () => {
    try {
      setStatus(await api<UploadStatus>("/api/upload-items/status"));
    } catch {
      /* header already reports an unreachable API */
    }
  }, []);

  useEffect(() => {
    void load();
    void loadStatus();
    const id = window.setInterval(() => {
      void loadStatus();
    }, 2000);
    return () => window.clearInterval(id);
  }, [load, loadStatus]);

  const running = !!status?.running;
  const wasRunning = useRef(false);

  // Tick once a second so the running row's Time cell advances.
  useEffect(() => {
    if (!running) {
      return;
    }
    setNowMs(Date.now());
    const id = window.setInterval(() => setNowMs(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [running]);

  // Refresh the overview once a publish run we observed running has ended.
  useEffect(() => {
    if (running) {
      wasRunning.current = true;
      return;
    }
    if (wasRunning.current) {
      wasRunning.current = false;
      void load();
    }
  }, [running, load]);

  const items = overview?.items ?? [];
  const production = live;
  const liveReady =
    production &&
    (!!overview?.live_enabled ||
      (running &&
        !!status?.live &&
        status?.target_env === "production"));
  const liveBlocked = production && !liveReady;
  const liveReason =
    (overview?.live_missing ?? []).join(", ") ||
    "EBAY_LIVE_UPLOAD_ENABLED is false";
  const allSelected = items.length > 0 && selected.length === items.length;
  // Only publish-run rows belong here; full/prepare runs are shown on Upload.
  const rows = status?.mode === "publish" ? status?.rows ?? [] : [];

  function toggle(asin: string) {
    setSelected((prev) =>
      prev.includes(asin) ? prev.filter((value) => value !== asin) : [...prev, asin],
    );
  }

  function toggleAll() {
    setSelected(allSelected ? [] : items.map((item) => item.asin));
  }

  async function publish(asins: string[]) {
    onError("");
    setMsg("Starting…");
    setBusy(true);
    try {
      const next = await api<UploadStatus>("/api/prepared/publish", {
        method: "POST",
        body: JSON.stringify({ asins }),
      });
      setStatus(next);
      setMsg(`Started ${next.run_id}`);
      setSelected([]);
      await load();
    } catch (e) {
      const text = e instanceof Error ? e.message : String(e);
      onError(text);
      setMsg(text);
    } finally {
      setBusy(false);
    }
  }

  async function publishLive(plan: LivePlan, confirm: string) {
    const asins = plan.items.map((item) => item.asin);
    const next = await api<UploadStatus>("/api/prepared/publish", {
      method: "POST",
      body: JSON.stringify(
        withPlanNonce(plan, { asins, confirm, batch_hash: plan.batch_hash }),
      ),
    });
    setStatus(next);
    setMsg(`Started live ${next.run_id}`);
    setSelected([]);
    await load();
  }

  async function stop() {
    onError("");
    try {
      setStatus(
        await api<UploadStatus>("/api/upload-items/stop", { method: "POST", body: "{}" }),
      );
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div className="panel grid upload-panel">
      <div className="upload-head">
        <div>
          <h2>Prepared — built but not live</h2>
          <p className="muted">
            Everything that was fetched, evaluated and drafted but is not on eBay yet. Putting
            an item live re-checks the Amazon price first and never regenerates the AI copy.
          </p>
        </div>
        <span className={production ? "upload-target live" : "upload-target"}>
          {production
            ? liveReady
              ? "LIVE (guarded)"
              : "LIVE disabled"
            : `-> ${overview?.target_env || "sandbox"} eBay`}
        </span>
      </div>
      {liveBlocked ? (
        <p className="upload-warning">
          Production live path is closed: {liveReason}. Nothing is sent to eBay until every
          gate is open. Switch to sandbox eBay in Settings to put prepared items live.
        </p>
      ) : null}
      {liveBannerVisible(status) ? (
        <div className="live-run-banner">PRODUCTION - real listings</div>
      ) : null}
      <div className="actions">
        <button type="button" disabled={busy} onClick={() => void load()}>
          Refresh
        </button>
        <button type="button" disabled={items.length === 0 || running} onClick={toggleAll}>
          {allSelected ? "Select none" : "Select all"}
        </button>
        {!production ? (
          <>
            <button
              type="button"
              className="primary"
              disabled={running || busy || selected.length === 0}
              onClick={() => void publish(selected)}
            >
              Put selected live ({selected.length})
            </button>
            <button
              type="button"
              disabled={running || busy || items.length === 0}
              onClick={() => void publish(items.map((item) => item.asin))}
            >
              Put all live
            </button>
          </>
        ) : liveReady ? (
          <LivePlanPanel
            mode="publish"
            asins={selected.length ? selected : items.map((item) => item.asin)}
            disabled={running || busy || items.length === 0}
            runLabel={
              selected.length
                ? `LIVE: publish selected (${selected.length})`
                : `LIVE: publish all (${items.length})`
            }
            onError={onError}
            onRun={publishLive}
          />
        ) : null}
        {running ? (
          <button type="button" onClick={() => void stop()}>
            Stop
          </button>
        ) : null}
        {msg ? <span className="muted">{msg}</span> : null}
      </div>
      <p className="muted">
        {status?.mode === "publish"
          ? running
            ? `Publish run ${status?.run_id || "…"} · ${status?.phase || "starting"}`
            : status?.run_id
              ? `Last run ${status.run_id} · ${status.phase}`
              : "No publish run yet."
          : running
            ? "Upload run in progress, see the Upload items tab."
            : "No publish run yet."}
        {status?.mode === "publish" && status?.error ? ` · ${status.error}` : ""}
      </p>
      <table>
        <thead>
          <tr>
            <th>
              <input
                type="checkbox"
                checked={allSelected}
                onChange={toggleAll}
                disabled={running}
                aria-label="Select all prepared items"
              />
            </th>
            <th>ASIN</th>
            <th>Title</th>
            <th>Price</th>
            <th>Margin</th>
            <th>Status</th>
            <th>Age</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.asin}>
              <td>
                <input
                  type="checkbox"
                  checked={selected.includes(item.asin)}
                  onChange={() => toggle(item.asin)}
                  aria-label={`Select ${item.asin}`}
                />
              </td>
              <td className="mono">{item.asin}</td>
              <td>{item.title}</td>
              <td className="mono">€{item.ebay_price.toFixed(2)}</td>
              <td className="mono">{formatMarginPct(item.margin.margin_pct)}</td>
              <td>{preparedStatusLabel(item.ebay_status)}</td>
              <td className="mono">{formatAgeDays(item.age_days)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {items.length === 0 ? (
        <p className="muted">
          Nothing prepared yet — use "Only prepare (no eBay)" on the Upload items tab.
        </p>
      ) : null}
      {status?.mode === "publish" ? (
        <RunProgressTable rows={rows} running={running} nowMs={nowMs} />
      ) : null}
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
  const [targetBusy, setTargetBusy] = useState(false);

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

  async function switchEbayTarget(env: "sandbox" | "production") {
    if (health?.ebay?.env === env) return;
    onError("");
    if (env === "production") {
      const ok = window.confirm(
        "Switch Dropship Desk to live eBay? Send and Publish will use your real seller account, not the sandbox."
      );
      if (!ok) return;
    }
    setTargetBusy(true);
    try {
      await api("/api/ebay/target", {
        method: "POST",
        body: JSON.stringify({ env }),
      });
      await refreshHealth();
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setTargetBusy(false);
    }
  }

  if (!margin || !shop) {
    return <div className="panel muted">Loading settings…</div>;
  }

  const live = health?.ebay?.env === "production";
  const connected = !!health?.ebay?.oauth_connected;
  const connectLabel = live
    ? connected
      ? "Reconnect live eBay"
      : "Connect live eBay"
    : connected
      ? "Reconnect sandbox eBay"
      : "Connect sandbox eBay";

  async function startOauth() {
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
        Target is per-app, not per listing. Sandbox and live keep separate OAuth tokens and offers.
        Live Send/Publish still needs <span className="mono">EBAY_AUTOMATION_ENABLED</span> and{" "}
        <span className="mono">EBAY_ALLOW_LIST</span> in <span className="mono">.env</span>, plus a
        confirm in this window.
      </p>
      <div className="ebay-target" role="group" aria-label="eBay target">
        <button
          type="button"
          className={health?.ebay?.env !== "production" ? "active" : ""}
          disabled={targetBusy}
          onClick={() => void switchEbayTarget("sandbox")}
        >
          Sandbox
        </button>
        <button
          type="button"
          className={health?.ebay?.env === "production" ? "active live" : ""}
          disabled={targetBusy}
          onClick={() => void switchEbayTarget("production")}
        >
          Live eBay
        </button>
      </div>
      {(health?.ebay?.production_gaps || []).length > 0 ? (
        <p className="error">
          Live is locked: missing {(health?.ebay?.production_gaps || []).join(", ")} in{" "}
          <span className="mono">.env</span>. Create a <strong>Production</strong> RuName at
          developer.ebay.com (not the sandbox one) with Auth accepted URL{" "}
          <span className="mono">https://127.0.0.1:8770/api/ebay/oauth/callback</span>
          , paste it as <span className="mono">EBAY_PROD_RUNAME</span>, then restart.
        </p>
      ) : null}
      <div className="oauth-card">
        <div>
          <span className={`badge ${connected ? "ok" : "fail"}`}>
            {waitingOauth
              ? "Waiting for browser…"
              : connected
                ? live
                  ? "Live eBay signed in"
                  : "Sandbox signed in"
                : live
                  ? "Live eBay not signed in"
                  : "Sandbox not signed in"}
          </span>
        </div>
        <ul className="oauth-facts">
          <li>
            Keys:{" "}
            {health?.ebay?.app_id_set && health?.ebay?.cert_id_set
              ? `present${health.ebay.app_id_hint ? ` (${health.ebay.app_id_hint})` : ""}`
              : "missing"}
          </li>
          <li>RuName: {health?.ebay?.runame_set ? "set" : "not set"}</li>
          <li>
            Send listings:{" "}
            {health?.ebay?.sell_allowed
              ? "allowed"
              : health?.ebay?.sell_block_reason || "blocked"}
          </li>
          <li>
            Other token: sandbox{" "}
            {health?.ebay?.sandbox_oauth_connected ? "saved" : "none"} · live{" "}
            {health?.ebay?.production_oauth_connected ? "saved" : "none"}
          </li>
        </ul>
        <div className="actions" style={{ marginTop: 0 }}>
          <button
            type="button"
            className={connected ? "" : "primary"}
            disabled={waitingOauth}
            onClick={() => void startOauth()}
          >
            {waitingOauth ? "Waiting for eBay…" : connectLabel}
          </button>
        </div>
        {connected ? (
          <p className="hint">
            You are already signed in. Reconnect only if tokens expire or you switched eBay users.
          </p>
        ) : (
          <p className="hint">
            Opens the eBay consent page. Chrome will warn about the local self-signed certificate —
            Advanced → Proceed (keep the <span className="mono">code=</span> in the URL).
          </p>
        )}
      </div>
      {!health?.ebay?.runame_set ? (
        <p className="muted">
          Put the RuName in{" "}
          <span className="mono">
            {health?.ebay?.env === "production" ? "EBAY_PROD_RUNAME" : "EBAY_SANDBOX_RUNAME"}
          </span>
          , then restart.
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
