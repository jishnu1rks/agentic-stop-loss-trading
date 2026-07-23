import { useEffect, useRef, useState, type ReactNode } from "react";
import { api } from "../api/client";
import type { Agent, OpenPositionPnl, Trade, TradeStats } from "../api/types";
import Modal from "./Modal";
import EditProtectionModal from "./EditProtectionModal";
import ChargesBreakdownModal from "./ChargesBreakdownModal";
import TradeDetailsModal from "./TradeDetailsModal";

type SortKey = keyof Trade;
type Period = "today" | "all" | "week" | "month" | "year";

// Period filtering, sorting, and stats aggregation all happen server-side
// now (GET /trades?period=...&sort_by=...&limit=...&offset=... and
// GET /trades/stats) so pagination can't produce wrong period totals or a
// cross-page sort order - see backend/app/routers/trades.py.
const PAGE_SIZE = 15;

function fmtDateOnly(d: string | null) {
  if (!d) return "—";
  return new Date(d).toLocaleDateString("en-IN", { dateStyle: "medium" });
}

function fmtMoney(n: number) {
  return n.toLocaleString("en-IN", { maximumFractionDigits: 0 });
}

type Column = {
  id: string;
  label: string;
  sortKey?: SortKey; // only sortable columns map to a Trade field
  headerTitle?: string;
  cell: (t: Trade, pnl?: OpenPositionPnl) => ReactNode;
  cellClassName?: (t: Trade, pnl?: OpenPositionPnl) => string;
};

export default function TradeLogTable({
  onChanged,
  lockedStatus,
  showPeriodFilter,
}: {
  onChanged?: () => void;
  lockedStatus?: "open" | "closed";
  title?: string;
  showPeriodFilter?: boolean;
}) {
  const [trades, setTrades] = useState<Trade[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [stats, setStats] = useState<TradeStats | null>(null);
  const [period, setPeriod] = useState<Period>("all");
  const [pnlByTradeId, setPnlByTradeId] = useState<Record<string, OpenPositionPnl>>({});
  const [agentNameById, setAgentNameById] = useState<Record<string, string>>({});
  const [agentStrategyById, setAgentStrategyById] = useState<Record<string, string>>({});
  const [statusFilter] = useState(lockedStatus ?? "");
  const [directionFilter] = useState("");
  const [exitReasonFilter] = useState("");
  const [sourceFilter] = useState(""); // "agent" | "manual" | ""
  const [sortKey, setSortKey] = useState<SortKey>("purchase_date");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [closingId, setClosingId] = useState<string | null>(null);
  const [confirmClose, setConfirmClose] = useState<Trade | null>(null);
  const [editTrade, setEditTrade] = useState<Trade | null>(null);
  // Two distinct popups, each with its own state so they never bleed into
  // each other: the charges & tax breakdown (History's Charges column) and
  // the full trade-details breakdown (either view's P&L column).
  const [chargesTrade, setChargesTrade] = useState<Trade | null>(null);
  const [detailsTrade, setDetailsTrade] = useState<Trade | null>(null);

  const isOpenView = lockedStatus === "open";
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  // Read inside loadPage via the ref (not the `trades` state binding) so an
  // IntersectionObserver callback created before the latest fetch settled
  // still computes the correct next offset - see the observer effect below.
  const tradesRef = useRef<Trade[]>(trades);
  tradesRef.current = trades;

  const filterParams = (): Record<string, string | number | boolean | undefined> => {
    const params: Record<string, string | number | boolean | undefined> = {
      sort_by: sortKey,
      sort_dir: sortDir,
    };
    if (statusFilter) params.status = statusFilter;
    if (directionFilter) params.direction = directionFilter;
    if (exitReasonFilter) params.exit_reason = exitReasonFilter;
    if (sourceFilter) params.is_manual = sourceFilter === "manual" ? "true" : "false";
    if (showPeriodFilter) params.period = period;
    return params;
  };

  // reset=true replaces the loaded set from offset 0 (mount, or any filter/
  // sort/period change); reset=false appends the next page (scroll-triggered
  // "load more" - only relevant on the paginated History view).
  const loadPage = (reset: boolean) => {
    const offset = reset ? 0 : tradesRef.current.length;
    const params = filterParams();
    if (showPeriodFilter) {
      params.limit = PAGE_SIZE;
      params.offset = offset;
    }
    if (!reset) setLoadingMore(true);
    api
      .listTrades(params)
      .then((page) => {
        setTrades((prev) => (reset ? page : [...prev, ...page]));
        setHasMore(showPeriodFilter ? page.length === PAGE_SIZE : false);
      })
      .catch(() => {
        if (reset) setTrades([]);
      })
      .finally(() => setLoadingMore(false));
  };

  useEffect(() => {
    loadPage(true);
    if (statusFilter !== "closed") {
      api.openPositionsPnl().then(setPnlByTradeId).catch(() => setPnlByTradeId({}));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusFilter, directionFilter, exitReasonFilter, sourceFilter, period, sortKey, sortDir]);

  // Stats (P&L/win-rate cards) are aggregated server-side over the whole
  // period-filtered set - independent of how many rows have been scrolled
  // into view, since `trades` is only ever a partial page once paginated.
  useEffect(() => {
    if (!showPeriodFilter) return;
    const params: Record<string, string | boolean | undefined> = { period };
    if (statusFilter) params.status = statusFilter;
    api.tradeStats(params).then(setStats).catch(() => setStats(null));
  }, [showPeriodFilter, statusFilter, period]);

  // Scroll-triggered "load more": watches a sentinel element rendered just
  // after the table rather than a specific scroll container, so it works
  // regardless of which ancestor actually scrolls.
  useEffect(() => {
    if (!showPeriodFilter || !hasMore) return;
    const el = sentinelRef.current;
    if (!el) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && !loadingMore) {
          loadPage(false);
        }
      },
      { rootMargin: "200px" },
    );
    observer.observe(el);
    return () => observer.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showPeriodFilter, hasMore, loadingMore]);

  useEffect(() => {
    api
      .listAgents()
      .then((agents: Agent[]) => {
        const names: Record<string, string> = {};
        const strategies: Record<string, string> = {};
        agents.forEach((a) => {
          names[a.agent_id] = a.name;
          strategies[a.agent_id] = a.strategy;
        });
        setAgentNameById(names);
        setAgentStrategyById(strategies);
      })
      .catch(() => {
        setAgentNameById({});
        setAgentStrategyById({});
      });
  }, []);

  // Unrealized P&L on open positions is only as fresh as the last fetch -
  // refresh it on a timer so the Net P&L column updates on its own instead
  // of only ever showing a stale price from whenever the page was opened.
  useEffect(() => {
    if (statusFilter === "closed") return;
    const id = setInterval(() => {
      api.openPositionsPnl().then(setPnlByTradeId).catch(() => {});
    }, 15 * 60 * 1000);
    return () => clearInterval(id);
  }, [statusFilter]);

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  };

  const handleClose = async (tradeId: string) => {
    setClosingId(tradeId);
    try {
      await api.closeTrade(tradeId);
      setConfirmClose(null);
      loadPage(true);
      onChanged?.();
    } catch (e) {
      alert(e instanceof Error ? e.message : "Failed to close trade");
    } finally {
      setClosingId(null);
    }
  };

  const afterEdit = () => {
    load();
    onChanged?.();
  };

  // ---- Column definitions (header + cell stay in sync; ordering is just
  // the order of this list, so moving a column is a one-line move) ----
  const netPnlCell = (t: Trade, pnl?: OpenPositionPnl): ReactNode => {
    const text =
      t.status === "open"
        ? pnl
          ? `${pnl.unrealized_pnl.toFixed(2)} (${pnl.unrealized_pnl_pct >= 0 ? "+" : ""}${pnl.unrealized_pnl_pct.toFixed(1)}%)`
          : "—"
        : t.net_profit != null
          ? `${t.net_profit.toFixed(2)}`
          : "—";
    return (
      <button className="editable-cell" title="Click to view all trade details" onClick={() => setDetailsTrade(t)}>
        {text}
      </button>
    );
  };
  const netPnlClass = (t: Trade, pnl?: OpenPositionPnl): string => {
    if (t.status === "open") return pnl ? (pnl.unrealized_pnl >= 0 ? "text-green" : "text-red") : "";
    return (t.net_profit ?? 0) >= 0 ? "text-green" : "text-red";
  };
  // Open Trades' CMP cell is colored by the same profit/loss sign that used
  // to color the P&L cell there - the P&L cell itself is intentionally
  // uncolored on that view now.
  const currentPriceClass = (t: Trade, pnl?: OpenPositionPnl): string => {
    if (t.status !== "open" || !pnl) return "";
    return pnl.unrealized_pnl >= 0 ? "text-green" : "text-red";
  };

  const cols: Record<string, Column> = {
    stock: {
      id: "stock",
      label: "Stock",
      sortKey: "stock_symbol",
      cell: (t) => (
        <>
          {t.stock_symbol} {t.is_manual && <span className="pill manual">manual</span>}
        </>
      ),
    },
    currentPrice: {
      id: "current_price",
      label: "CMP",
      cell: (t, pnl) => (t.status === "open" && pnl ? `${pnl.current_price.toFixed(2)}` : "—"),
      cellClassName: currentPriceClass,
    },
    direction: {
      id: "direction",
      label: "",
      sortKey: "direction",
      cell: (t) => <span className={`pill ${t.direction}`}>{t.direction}</span>,
    },
    qty: { id: "qty", label: "Qty", sortKey: "quantity", cell: (t) => t.quantity },
    buyPrice: {
      id: "buy_price",
      label: "Buy price",
      sortKey: "buy_price",
      cell: (t) => `${t.buy_price.toFixed(2)}`,
    },
    stopLoss: {
      id: "stop_loss",
      label: "Stop loss",
      sortKey: "stop_loss_price",
      cell: (t) => {
        const value = t.stop_loss_price
          ? `${t.stop_loss_price.toFixed(2)}${t.stop_loss_pct ? ` (-${t.stop_loss_pct.toFixed(1)}%)` : ""}`
          : "—";
        return t.status === "open" ? (
          <button className="editable-cell" title="Click to edit stop-loss / target" onClick={() => setEditTrade(t)}>
            {value}
          </button>
        ) : (
          value
        );
      },
    },
    target: {
      id: "target",
      label: "Target",
      sortKey: "target_price",
      cell: (t) => {
        const value =
          t.target_price != null
            ? `${t.target_price.toFixed(2)}${t.target_pct != null ? ` (${t.target_pct.toFixed(1)}%)` : ""}`
            : "—";
        return t.status === "open" ? (
          <button className="editable-cell" title="Click to edit stop-loss / target" onClick={() => setEditTrade(t)}>
            {value}
          </button>
        ) : (
          value
        );
      },
    },
    buyDate: {
      id: "buy_date",
      label: "Buy date",
      sortKey: "purchase_date",
      cell: (t) => fmtDateOnly(t.purchase_date),
    },
    sellDate: { id: "sell_date", label: "Sell date", sortKey: "sell_date", cell: (t) => fmtDateOnly(t.sell_date) },
    investmentAmount: {
      id: "investment_amount",
      label: "Investment",
      cell: (t) => `${(t.buy_price * t.quantity).toFixed(2)}`,
    },
    profitLoss: {
      id: "profit_loss",
      label: "Profit/Loss",
      sortKey: "gross_profit",
      cell: (t) =>
        t.gross_profit != null ? (
          <button className="editable-cell" title="Click to view all trade details" onClick={() => setDetailsTrade(t)}>
            {t.gross_profit.toFixed(2)}
          </button>
        ) : (
          "—"
        ),
      cellClassName: (t) => (t.gross_profit != null ? (t.gross_profit >= 0 ? "text-green" : "text-red") : ""),
    },
    netPnl: { id: "net_pnl", label: "Net P&L", sortKey: "net_profit", cell: netPnlCell, cellClassName: netPnlClass },
    // Open Trades view: same figure as netPnlCell (unrealized P&L isn't
    // really "net" vs "gross" - there's no exit charge/tax yet to net out),
    // just relabeled and left uncolored since CMP carries the color there now.
    openPnl: { id: "open_pnl", label: "P & L", sortKey: "net_profit", cell: netPnlCell },
    charges: {
      id: "charges",
      label: "Charges",
      sortKey: "charges",
      cell: (t) =>
        t.charges != null ? (
          <button className="editable-cell" title="Click to view charges & tax breakdown" onClick={() => setChargesTrade(t)}>
            {t.charges.toFixed(2)}
          </button>
        ) : (
          "—"
        ),
    },
    mode: {
      id: "mode",
      label: "Agent",
      cell: (t) => {
        if (t.is_manual) return <span title="Manual trade">👆</span>;
        // An Execution agent's own name isn't the interesting info here -
        // show the Recommending agent whose signal actually led to this
        // trade instead (source_agent_id, populated since that field was
        // added; older execution trades predate it and show nothing extra).
        const actingStrategy = t.agent_id ? agentStrategyById[t.agent_id] : undefined;
        const displayAgentId = actingStrategy === "llm_recommendation_execution" ? t.source_agent_id : t.agent_id;
        const label = displayAgentId ? (agentNameById[displayAgentId] ?? displayAgentId) : "";
        return <span title={label}>🤖 {label}</span>;
      },
    },
    actions: {
      id: "actions",
      label: "",
      cell: (t) =>
        t.status === "open" ? (
          <button className="btn btn-close" onClick={() => setConfirmClose(t)}>
            Exit
          </button>
        ) : null,
    },
  };

  // Open Trades: compact view - Current price up front, no date/charges/tax
  // (always empty on open positions), no filters. History (and the unlocked
  // all-statuses view) keeps the full set since those columns are meaningful
  // once a trade has closed.
  const columns: Column[] = isOpenView
    ? [
        cols.stock,
        cols.direction,
        cols.qty,
        cols.currentPrice,
        cols.openPnl,
        cols.stopLoss,
        cols.target,
        cols.mode,
        cols.actions,
      ]
    : [
        cols.stock,
        cols.investmentAmount,
        cols.profitLoss,
        cols.charges,
        cols.netPnl,
        cols.buyDate,
        cols.sellDate,
        cols.mode,
      ];

  return (
    <>
      {showPeriodFilter && (
        <>
          <div className="period-filter">
            {(["today", "all", "week", "month", "year"] as Period[]).map((p) => (
              <button key={p} className={p === period ? "active" : ""} onClick={() => setPeriod(p)}>
                {p === "today" ? "Today" : p === "all" ? "All time" : `This ${p}`}
              </button>
            ))}
          </div>

          {stats && (
            <div className="kpi-grid" style={{ marginBottom: 14 }}>
              <div className="kpi-card">
                <div className="label">Capital</div>
                <div className={`value ${stats.current_capital >= stats.capital_at_period_start ? "positive" : "negative"}`}>
                  {fmtMoney(stats.current_capital)}
                </div>
                <div className="subvalue">
                  Started {fmtMoney(stats.capital_at_period_start)}
                  {stats.first_trade_date ? ` on ${fmtDateOnly(stats.first_trade_date)}` : ""}
                </div>
              </div>
              <div className="kpi-card">
                <div className="label">P &amp; L</div>
                <div className={`value ${stats.gross_pnl >= 0 ? "positive" : "negative"}`}>{fmtMoney(stats.gross_pnl)}</div>
              </div>
              <div className="kpi-card">
                <div className="label">Net P &amp; L</div>
                <div className={`value ${stats.net_pnl >= 0 ? "positive" : "negative"}`}>{fmtMoney(stats.net_pnl)}</div>
                <div className="subvalue">{fmtMoney(stats.charges)} charges &amp; {fmtMoney(stats.tax)} tax</div>
              </div>
              <div className="kpi-card">
                <div className="label">Trades</div>
                <div className="value">{stats.count}</div>
              </div>
              <div className="kpi-card">
                <div className="label">Win rate</div>
                <div className="value">{stats.win_rate.toFixed(1)}%</div>
              </div>
            </div>
          )}
        </>
      )}

    <div className="panel">
      {trades.length === 0 ? (
        <div className="empty-state">{isOpenView ? "No open trades yet" : "No trades match these filters"}</div>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table>
            <thead>
              <tr>
                {columns.map((c) => (
                  <th
                    key={c.id}
                    title={c.headerTitle}
                    onClick={c.sortKey ? () => toggleSort(c.sortKey!) : undefined}
                    style={c.sortKey ? undefined : { cursor: "default" }}
                  >
                    {c.label}
                    {c.sortKey && sortKey === c.sortKey ? (sortDir === "asc" ? " ▲" : " ▼") : ""}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {trades.map((t) => {
                const pnl = pnlByTradeId[t.trade_id];
                return (
                  <tr key={t.trade_id}>
                    {columns.map((c) => (
                      <td key={c.id} className={c.cellClassName?.(t, pnl)}>
                        {c.cell(t, pnl)}
                      </td>
                    ))}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {showPeriodFilter && hasMore && (
        <div ref={sentinelRef} className="text-dim" style={{ textAlign: "center", padding: 12, fontSize: 12 }}>
          {loadingMore ? "Loading more…" : ""}
        </div>
      )}

      {confirmClose && (
        <Modal
          title="Close position?"
          onClose={() => setConfirmClose(null)}
          footer={
            <>
              <button className="btn btn-neutral" onClick={() => setConfirmClose(null)} disabled={closingId != null}>
                Cancel
              </button>
              <button className="btn btn-sell" onClick={() => handleClose(confirmClose.trade_id)} disabled={closingId != null}>
                {closingId ? "Closing…" : "Close position"} 
              </button>
            </>
          }
        >
          <p style={{ margin: 0, fontSize: 14, lineHeight: 1.5 }}>
            Close <strong>{confirmClose.quantity} {confirmClose.stock_symbol}</strong> ({confirmClose.direction}) at the
            current market price? This exits the position immediately and cancels its stop-loss / target orders.
          </p>
        </Modal>
      )}

      {editTrade && (
        <EditProtectionModal
          trade={editTrade}
          pnl={pnlByTradeId[editTrade.trade_id]}
          agentName={editTrade.agent_id ? (agentNameById[editTrade.agent_id] ?? editTrade.agent_id) : "Manual"}
          onClose={() => setEditTrade(null)}
          onSaved={afterEdit}
        />
      )}

      {chargesTrade && <ChargesBreakdownModal trade={chargesTrade} onClose={() => setChargesTrade(null)} />}

      {detailsTrade && (
        <TradeDetailsModal
          trade={detailsTrade}
          pnl={pnlByTradeId[detailsTrade.trade_id]}
          agentName={detailsTrade.agent_id ? (agentNameById[detailsTrade.agent_id] ?? detailsTrade.agent_id) : "Manual"}
          onClose={() => setDetailsTrade(null)}
        />
      )}
    </div>
    </>
  );
}
