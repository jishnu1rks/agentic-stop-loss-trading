import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Agent, Recommendation } from "../api/types";

const RECO_REFRESH_INTERVAL_MS = 15 * 60 * 1000;
const RECO_CACHE_STORAGE_KEY = "reco-cache-v1";

type RecoCache = {
  agents: Agent[];
  recosByAgent: Record<string, Recommendation[]>;
  fetchedAt: number;
};

function loadPersistedRecoCache(): RecoCache | null {
  try {
    const raw = localStorage.getItem(RECO_CACHE_STORAGE_KEY);
    return raw ? (JSON.parse(raw) as RecoCache) : null;
  } catch {
    return null;
  }
}

function persistRecoCache(cache: RecoCache) {
  try {
    localStorage.setItem(RECO_CACHE_STORAGE_KEY, JSON.stringify(cache));
  } catch {
    // localStorage unavailable/full - the in-memory cache below still works for this tab.
  }
}

// Module-level (not component state), seeded from localStorage, so
// recommendations survive both this panel unmounting (dashboard view
// switches) and a full page reload - without re-hitting the recommendations
// endpoint each time. Only a genuinely 15-minute-stale cache triggers a
// refetch; until then, every remount/reload renders straight from here.
let recoCache: RecoCache | null = loadPersistedRecoCache();

function fetchRecommendations(
  setAgents: (agents: Agent[]) => void,
  setRecosByAgent: (fn: (prev: Record<string, Recommendation[]>) => Record<string, Recommendation[]>) => void,
  force = false,
): Promise<void> {
  return api.listAgents().then((all) => {
    const recoAgents = all.filter(
      (a) =>
        a.strategy === "momentum_breakout" ||
        a.strategy === "llm_recommendation" ||
        a.strategy === "llm_recommendation_execution",
    );
    setAgents(recoAgents);

    const recosByAgent: Record<string, Recommendation[]> = {};

    // Persisting is deferred until every agent has settled (see below) -
    // writing a partial cache here would tag an interrupted load as
    // "fresh" (isStale checks only fetchedAt), leaving the panel stuck on
    // "fetching recommendations..." for up to RECO_REFRESH_INTERVAL_MS on
    // the next mount even though nothing is actually in flight anymore.
    return Promise.allSettled(
      recoAgents.map((a) =>
        api
          .agentRecommendations(a.agent_id, force)
          .then((recos) => recos.map((r) => ({ ...r, strategy: a.strategy, agentName: a.name })))
          .catch(() => [] as Recommendation[])
          .then((tagged) => {
            recosByAgent[a.agent_id] = tagged;
            setRecosByAgent((prev) => ({ ...prev, [a.agent_id]: tagged }));
          }),
      ),
    ).then(() => {
      recoCache = { agents: recoAgents, recosByAgent, fetchedAt: Date.now() };
      persistRecoCache(recoCache);
    });
  });
}

function fmtPrice(n: number | undefined | null) {
  if (n == null) return "—";
  return `${n.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
}

const CAP_SIZE_LABELS: Record<string, string> = { large: "Large cap", mid: "Mid cap", small: "Small cap" };

function RecommendationCard({ reco, onBought }: { reco: Recommendation; onBought?: () => void }) {
  const [buying, setBuying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [bought, setBought] = useState(false);

  if (reco.unavailable) {
    return (
      <div className="reco-card">
        <div className="reco-header">
          <div className="reco-avatar">{reco.symbol.slice(0, 2)}</div>
          <div>
            <div className="reco-symbol">{reco.symbol}</div>
            <div className="reco-timestamp">data unavailable</div>
          </div>
        </div>
        <div className="empty-state">{reco.reason ?? "Could not fetch a live price for this symbol."}</div>
      </div>
    );
  }

  const isIdeaOnly = reco.strategy === "llm_recommendation";
  const isLlmSignal = reco.strategy === "llm_recommendation_execution";
  const confirmed = reco.in_signal === true;
  const canBuy = (reco.quantity ?? 0) > 0 && !reco.already_open;

  if (isIdeaOnly) {
    return (
      <div className="reco-card">
        <div className="reco-header">
          <div className="reco-avatar">{reco.symbol.slice(0, 2)}</div>
          <div>
            <div className="reco-symbol">{reco.symbol}</div>
            <div className="reco-timestamp">
              {new Date().toLocaleDateString("en-IN", { day: "2-digit", month: "short" })}
              {reco.cap_size && ` · ${CAP_SIZE_LABELS[reco.cap_size]}`}
              {reco.agentName && ` · ${reco.agentName}`}
            </div>
          </div>
          <span className={`pill ${reco.direction === "sell" ? "sell" : "buy"}`}>
            {reco.direction === "sell" ? "SELL IDEA" : "BUY IDEA"}
          </span>
        </div>

        <div className="reco-cmp-row">
          <div>
            <div className="reco-cmp-label">CMP</div>
            <div className="reco-cmp-value">{fmtPrice(reco.cmp)}</div>
          </div>
        </div>

        <div className="reco-detail-grid">
          <div>
            <div className="reco-detail-label">Prior high</div>
            <div className="reco-detail-value">{fmtPrice(reco.prior_high)}</div>
          </div>
          <div>
            <div className="reco-detail-label">Target (+upside)</div>
            <div className="reco-detail-value text-green">
              {fmtPrice(reco.target_price)}
              {reco.upside_pct != null ? ` (+${reco.upside_pct.toFixed(1)}%)` : ""}
            </div>
          </div>
          <div>
            <div className="reco-detail-label">Stop loss</div>
            <div className="reco-detail-value text-red">{fmtPrice(reco.stop_loss_price)}</div>
          </div>
          <div>
            <div className="reco-detail-label">Qty (at this size)</div>
            <div className="reco-detail-value">{reco.quantity}</div>
          </div>
        </div>

        <div className="reco-rationale">{reco.rationale}</div>
        {reco.already_open && <div className="reco-open-badge">● Position already open for this symbol</div>}
      </div>
    );
  }

  const handleBuy = async () => {
    setBuying(true);
    setError(null);
    try {
      const cmp = reco.cmp!;
      const stopLossPct = reco.stop_loss_price != null ? ((cmp - reco.stop_loss_price) / cmp) * 100 : undefined;
      const targetPct = reco.target_price != null ? ((reco.target_price - cmp) / cmp) * 100 : undefined;
      await api.placeManualTrade({
        stock_symbol: reco.symbol,
        direction: "buy",
        quantity: reco.quantity!,
        stop_loss_pct: stopLossPct,
        target_pct: targetPct,
      });
      setBought(true);
      onBought?.();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail ?? "Failed to place trade");
    } finally {
      setBuying(false);
    }
  };

  return (
    <div className="reco-card">
      <div className="reco-header">
        <div className="reco-avatar">{reco.symbol.slice(0, 2)}</div>
        <div>
          <div className="reco-symbol">{reco.symbol}</div>
          <div className="reco-timestamp">
            {new Date().toLocaleDateString("en-IN", { day: "2-digit", month: "short" })}
            {reco.cap_size && ` · ${CAP_SIZE_LABELS[reco.cap_size]}`}
            {isLlmSignal && reco.source_agent_name && ` · via ${reco.source_agent_name}`}
          </div>
        </div>
        <span
          className={`pill ${isLlmSignal ? (reco.direction === "sell" ? "sell" : "buy") : confirmed ? "buy" : "open"}`}
        >
          {isLlmSignal
            ? reco.direction === "sell"
              ? "SELL SIGNAL"
              : "BUY SIGNAL"
            : confirmed
              ? "BREAKOUT"
              : "WATCHING"}
        </span>
      </div>

      <div className="reco-progress-track">
        <div
          className={`reco-progress-fill ${confirmed ? "buy" : "sell"}`}
          style={{ width: `${reco.proximity_pct ?? 0}%` }}
        />
      </div>

      <div className="reco-cmp-row">
        <div>
          <div className="reco-cmp-label">CMP</div>
          <div className="reco-cmp-value">{fmtPrice(reco.cmp)}</div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div className="reco-cmp-label">vs {reco.prior_high != null ? "prior high" : "band"}</div>
          <div className={(reco.breakout_pct ?? 0) >= 0 ? "text-green" : "text-red"} style={{ fontWeight: 700 }}>
            {reco.breakout_pct != null ? `${reco.breakout_pct >= 0 ? "+" : ""}${reco.breakout_pct.toFixed(1)}%` : "—"}
          </div>
        </div>
      </div>

      <div className="reco-detail-grid">
        <div>
          <div className="reco-detail-label">Prior high</div>
          <div className="reco-detail-value">{fmtPrice(reco.prior_high)}</div>
        </div>
        <div>
          <div className="reco-detail-label">Target (+upside)</div>
          <div className="reco-detail-value text-green">
            {fmtPrice(reco.target_price)}
            {reco.upside_pct != null ? ` (+${reco.upside_pct.toFixed(1)}%)` : ""}
          </div>
        </div>
        <div>
          <div className="reco-detail-label">Stop loss</div>
          <div className="reco-detail-value text-red">{fmtPrice(reco.stop_loss_price)}</div>
        </div>
        <div>
          <div className="reco-detail-label">Qty (at this size)</div>
          <div className="reco-detail-value">{reco.quantity}</div>
        </div>
      </div>

      <div className="reco-rationale">{reco.rationale}</div>
      {reco.already_open && <div className="reco-open-badge">● Position already open for this symbol</div>}
      {error && <div className="reco-rationale text-red">{error}</div>}

      <button
        className="btn btn-buy"
        style={{ width: "100%", marginTop: 12 }}
        disabled={!canBuy || buying || bought}
        onClick={handleBuy}
      >
        {bought
          ? "Bought"
          : buying
            ? "Buying…"
            : reco.already_open
              ? "Already open"
              : (reco.quantity ?? 0) <= 0
                ? "Qty too small"
                : `Buy ${reco.quantity}`}
      </button>
    </div>
  );
}

type CapFilter = "all" | "large" | "mid" | "small";

const CAP_FILTER_OPTIONS: { value: CapFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "large", label: "Large cap" },
  { value: "mid", label: "Mid cap" },
  { value: "small", label: "Small cap" },
];

export default function RecommendationsPanel({ onBought }: { onBought?: () => void }) {
  const [agents, setAgents] = useState<Agent[]>(recoCache?.agents ?? []);
  const [recosByAgent, setRecosByAgent] = useState<Record<string, Recommendation[]>>(
    recoCache?.recosByAgent ?? {},
  );
  const [capFilter, setCapFilter] = useState<CapFilter>("all");
  const [forcing, setForcing] = useState(false);

  const forceRescan = () => {
    setForcing(true);
    fetchRecommendations(setAgents, setRecosByAgent, true).finally(() => setForcing(false));
  };

  useEffect(() => {
    const isStale = recoCache === null || Date.now() - recoCache.fetchedAt >= RECO_REFRESH_INTERVAL_MS;
    if (isStale) {
      fetchRecommendations(setAgents, setRecosByAgent);
    }

    // Keep refreshing on the same cadence for as long as the panel stays
    // mounted, rather than only re-checking staleness on the next remount.
    const interval = setInterval(
      () => fetchRecommendations(setAgents, setRecosByAgent),
      RECO_REFRESH_INTERVAL_MS,
    );
    return () => clearInterval(interval);
  }, []);

  const allRecos = agents.flatMap((a) => recosByAgent[a.agent_id] ?? []);
  const loaded = agents.length > 0 && agents.every((a) => a.agent_id in recosByAgent);

  // An Execution agent mirrors the Recommending agent's own signals, so a
  // symbol that already has an actionable BUY/SELL SIGNAL card doesn't also
  // need the non-actionable idea-only card for the same symbol - it's the
  // same underlying recommendation, and showing both is just confusing
  // duplication rather than new information.
  const executionSymbols = new Set(
    allRecos.filter((r) => r.strategy === "llm_recommendation_execution").map((r) => r.symbol),
  );
  const dedupedRecos = allRecos.filter(
    (r) => !(r.strategy === "llm_recommendation" && executionSymbols.has(r.symbol)),
  );

  const filteredRecos = capFilter === "all" ? dedupedRecos : dedupedRecos.filter((r) => r.cap_size === capFilter);
  const confirmedCount = filteredRecos.filter((r) => r.in_signal).length;

  return (
    <div className="panel">
      <div className="panel-header">
        <h3>Latest Recommendations</h3>
        {/* <span className="text-dim" style={{ fontSize: 12 }}>
          Live scan across each agent's configured stocks (momentum breakout and AI recommendation agents)
        </span> */}
        <button
          className="btn"
          style={{ padding: "4px 12px", fontSize: 12 }}
          disabled={forcing}
          onClick={forceRescan}
          title="Bypasses the 1-hour/11:00-15:00 AI scan limit for testing - runs a real scan right now"
        >
          {forcing ? "Rescanning…" : "Force rescan"}
        </button>
      </div>
      {agents.length === 0 ? (
        <div className="empty-state">No recommendation agents configured yet</div>
      ) : !loaded ? (
        <div className="empty-state">fetching recommendations...</div>
      ) : allRecos.length === 0 ? (
        <div className="empty-state">No results found.</div>
      ) : (
        <>
          <div className="cap-filter-tabs" style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
            {CAP_FILTER_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                className={`btn ${capFilter === opt.value ? "btn-buy" : ""}`}
                style={{ padding: "4px 12px", fontSize: 12 }}
                onClick={() => setCapFilter(opt.value)}
              >
                {opt.label}
              </button>
            ))}
          </div>

          {filteredRecos.length === 0 ? (
            <div className="empty-state">No results for this filter.</div>
          ) : (
            <>
              {confirmedCount === 0 && (
                <div className="reco-rationale" style={{ marginBottom: 12, borderTop: "none", paddingTop: 0 }}>
                  No confirmed breakouts right now - showing the closest matches, ranked, none of these have actually
                  cleared the breakout threshold with volume confirmation yet.
                </div>
              )}
              <div className="reco-grid">
                {filteredRecos.map((reco) => (
                  <RecommendationCard key={reco.symbol} reco={reco} onBought={onBought} />
                ))}
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
}
