import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Agent, Recommendation } from "../api/types";

const RECO_REFRESH_INTERVAL_MS = 15 * 60 * 1000;

// Module-level (not component state) so recommendations survive this panel
// unmounting - it remounts on every dashboard view switch and on every
// manual refresh - without re-hitting the recommendations endpoint each
// time. Only a genuinely 15-minute-stale cache triggers a refetch.
let recoCache: {
  agents: Agent[];
  recosByAgent: Record<string, Recommendation[]>;
  fetchedAt: number;
} | null = null;

function fetchRecommendations(
  setAgents: (agents: Agent[]) => void,
  setRecosByAgent: (fn: (prev: Record<string, Recommendation[]>) => Record<string, Recommendation[]>) => void,
) {
  api.listAgents().then((all) => {
    const momentumAgents = all.filter((a) => a.strategy === "momentum_breakout");
    setAgents(momentumAgents);

    const recosByAgent: Record<string, Recommendation[]> = {};
    recoCache = { agents: momentumAgents, recosByAgent, fetchedAt: Date.now() };

    momentumAgents.forEach((a) => {
      api
        .agentRecommendations(a.agent_id)
        .then((recos) => {
          recosByAgent[a.agent_id] = recos;
          setRecosByAgent((prev) => ({ ...prev, [a.agent_id]: recos }));
        })
        .catch(() => {
          recosByAgent[a.agent_id] = [];
          setRecosByAgent((prev) => ({ ...prev, [a.agent_id]: [] }));
        });
    });
  });
}

function fmtPrice(n: number | undefined | null) {
  if (n == null) return "—";
  return `${n.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
}

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

  const confirmed = reco.in_signal === true;
  const canBuy = (reco.quantity ?? 0) > 0 && !reco.already_open;

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
          <div className="reco-timestamp">{new Date().toLocaleDateString("en-IN", { day: "2-digit", month: "short" })}</div>
        </div>
        <span className={`pill ${confirmed ? "buy" : "open"}`}>{confirmed ? "BREAKOUT" : "WATCHING"}</span>
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

export default function RecommendationsPanel({ onBought }: { onBought?: () => void }) {
  const [agents, setAgents] = useState<Agent[]>(recoCache?.agents ?? []);
  const [recosByAgent, setRecosByAgent] = useState<Record<string, Recommendation[]>>(
    recoCache?.recosByAgent ?? {},
  );

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
  const confirmedCount = allRecos.filter((r) => r.in_signal).length;

  return (
    <div className="panel">
      <div className="panel-header">
        <h3>Latest Recommendations</h3>
        <span className="text-dim" style={{ fontSize: 12 }}>
          Momentum breakout scan across the agent's universe (live NSE prices)
        </span>
      </div>
      {agents.length === 0 ? (
        <div className="empty-state">No momentum_breakout agents configured yet</div>
      ) : !loaded ? (
        <div className="empty-state">Scanning</div>
      ) : allRecos.length === 0 ? (
        <div className="empty-state">No candidates found.</div>
      ) : (
        <>
          {confirmedCount === 0 && (
            <div className="reco-rationale" style={{ marginBottom: 12, borderTop: "none", paddingTop: 0 }}>
              No confirmed breakouts right now - showing the closest candidates, ranked, none of these have actually
              cleared the breakout threshold with volume confirmation yet.
            </div>
          )}
          <div className="reco-grid">
            {allRecos.map((reco) => (
              <RecommendationCard key={reco.symbol} reco={reco} onBought={onBought} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
