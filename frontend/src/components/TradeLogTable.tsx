import { useEffect, useMemo, useState, type ReactNode } from "react";
import { api } from "../api/client";
import type { Agent, OpenPositionPnl, Trade } from "../api/types";
import Modal from "./Modal";
import EditProtectionModal from "./EditProtectionModal";
import ChargesBreakdownModal from "./ChargesBreakdownModal";
import TradeDetailsModal from "./TradeDetailsModal";

type SortKey = keyof Trade;

function fmtDateOnly(d: string | null) {
  if (!d) return "—";
  return new Date(d).toLocaleDateString("en-IN", { dateStyle: "medium" });
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
}: {
  onChanged?: () => void;
  lockedStatus?: "open" | "closed";
  title?: string;
}) {
  const [trades, setTrades] = useState<Trade[]>([]);
  const [pnlByTradeId, setPnlByTradeId] = useState<Record<string, OpenPositionPnl>>({});
  const [agentNameById, setAgentNameById] = useState<Record<string, string>>({});
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

  const load = () => {
    const params: Record<string, string> = {};
    if (statusFilter) params.status = statusFilter;
    if (directionFilter) params.direction = directionFilter;
    if (exitReasonFilter) params.exit_reason = exitReasonFilter;
    if (sourceFilter) params.is_manual = sourceFilter === "manual" ? "true" : "false";
    api.listTrades(params).then(setTrades).catch(() => setTrades([]));
    if (statusFilter !== "closed") {
      api.openPositionsPnl().then(setPnlByTradeId).catch(() => setPnlByTradeId({}));
    }
  };

  useEffect(load, [statusFilter, directionFilter, exitReasonFilter, sourceFilter]);

  useEffect(() => {
    api
      .listAgents()
      .then((agents: Agent[]) => {
        const map: Record<string, string> = {};
        agents.forEach((a) => {
          map[a.agent_id] = a.name;
        });
        setAgentNameById(map);
      })
      .catch(() => setAgentNameById({}));
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

  const sorted = useMemo(() => {
    const copy = [...trades];
    copy.sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      if (av < bv) return sortDir === "asc" ? -1 : 1;
      if (av > bv) return sortDir === "asc" ? 1 : -1;
      return 0;
    });
    return copy;
  }, [trades, sortKey, sortDir]);

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
      load();
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
      cell: (t) => (t.gross_profit != null ? `${t.gross_profit.toFixed(2)}` : "—"),
      cellClassName: (t) => (t.gross_profit != null ? (t.gross_profit >= 0 ? "text-green" : "text-red") : ""),
    },
    netPnl: { id: "net_pnl", label: "Net P&L", sortKey: "net_profit", cell: netPnlCell, cellClassName: netPnlClass },
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
      label: "Mode",
      cell: (t) => (
        <span title={t.is_manual ? "Manual" : (t.agent_id ? (agentNameById[t.agent_id] ?? t.agent_id) : "Agent")}>
          {t.is_manual ? "👆" : "🤖"}
        </span>
      ),
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
        cols.buyPrice,
        cols.qty,
        cols.currentPrice,
        cols.stopLoss,
        cols.target,
        cols.netPnl,
        cols.mode,
        cols.actions,
      ]
    : [
        cols.stock,
        cols.buyDate,
        cols.sellDate,
        cols.investmentAmount,
        cols.profitLoss,
        cols.charges,
        cols.netPnl,
        cols.mode,
      ];

  return (
    <div className="panel">
      {sorted.length === 0 ? (
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
              {sorted.map((t) => {
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
  );
}
