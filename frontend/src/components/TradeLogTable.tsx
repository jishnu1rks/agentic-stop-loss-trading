import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { Trade } from "../api/types";

type SortKey = keyof Trade;

function fmtDate(d: string | null) {
  if (!d) return "—";
  return new Date(d).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" });
}

export default function TradeLogTable({
  onChanged,
  lockedStatus,
  title,
}: {
  onChanged?: () => void;
  lockedStatus?: "open" | "closed";
  title?: string;
}) {
  const [trades, setTrades] = useState<Trade[]>([]);
  const [statusFilter, setStatusFilter] = useState(lockedStatus ?? "");
  const [directionFilter, setDirectionFilter] = useState("");
  const [exitReasonFilter, setExitReasonFilter] = useState("");
  const [sourceFilter, setSourceFilter] = useState(""); // "agent" | "manual" | ""
  const [sortKey, setSortKey] = useState<SortKey>("purchase_date");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [closingId, setClosingId] = useState<string | null>(null);

  const load = () => {
    const params: Record<string, string> = {};
    if (statusFilter) params.status = statusFilter;
    if (directionFilter) params.direction = directionFilter;
    if (exitReasonFilter) params.exit_reason = exitReasonFilter;
    if (sourceFilter) params.is_manual = sourceFilter === "manual" ? "true" : "false";
    api.listTrades(params).then(setTrades).catch(() => setTrades([]));
  };

  useEffect(load, [statusFilter, directionFilter, exitReasonFilter, sourceFilter]);

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
      load();
      onChanged?.();
    } catch (e) {
      alert(e instanceof Error ? e.message : "Failed to close trade");
    } finally {
      setClosingId(null);
    }
  };

  const headers: { key: SortKey; label: string }[] = [
    { key: "stock_symbol", label: "Stock" },
    { key: "direction", label: "Direction" },
    { key: "quantity", label: "Qty" },
    { key: "buy_price", label: "Buy price" },
    { key: "sell_price", label: "Sell price" },
    { key: "stop_loss_price", label: "Stop loss" },
    { key: "target_price", label: "Target" },
    { key: "purchase_date", label: "Purchase date" },
    { key: "sell_date", label: "Sell date" },
    { key: "net_profit", label: "Net P&L" },
    { key: "charges", label: "Charges" },
    { key: "tax", label: "Tax" },
    { key: "exit_reason", label: "Exit reason" },
    { key: "status", label: "Status" },
  ];

  return (
    <div className="panel">
      {title && (
        <div className="panel-header">
          <h3>{title}</h3>
        </div>
      )}
      <div className="filters">
        {!lockedStatus && (
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
            <option value="">All statuses</option>
            <option value="open">Open</option>
            <option value="closed">Closed</option>
            <option value="error">Error</option>
          </select>
        )}
        <select value={directionFilter} onChange={(e) => setDirectionFilter(e.target.value)}>
          <option value="">All directions</option>
          <option value="buy">Buy</option>
          <option value="sell">Sell</option>
        </select>
        <select value={exitReasonFilter} onChange={(e) => setExitReasonFilter(e.target.value)}>
          <option value="">All exit reasons</option>
          <option value="stop_loss">Stop-loss</option>
          <option value="target">Target</option>
          <option value="manual">Manual</option>
          <option value="timeout">Timeout</option>
        </select>
        <select value={sourceFilter} onChange={(e) => setSourceFilter(e.target.value)}>
          <option value="">Agent + manual</option>
          <option value="agent">Agent trades only</option>
          <option value="manual">Manual trades only</option>
        </select>
      </div>

      {sorted.length === 0 ? (
        <div className="empty-state">No trades match these filters</div>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table>
            <thead>
              <tr>
                {headers.map((h) => (
                  <th key={h.key} onClick={() => toggleSort(h.key)}>
                    {h.label}
                    {sortKey === h.key ? (sortDir === "asc" ? " ▲" : " ▼") : ""}
                  </th>
                ))}
                <th />
              </tr>
            </thead>
            <tbody>
              {sorted.map((t) => (
                <tr key={t.trade_id}>
                  <td>
                    {t.stock_symbol} {t.is_manual && <span className="pill manual">manual</span>}
                  </td>
                  <td>
                    <span className={`pill ${t.direction}`}>{t.direction}</span>
                  </td>
                  <td>{t.quantity}</td>
                  <td>₹{t.buy_price.toFixed(2)}</td>
                  <td>{t.sell_price != null ? `₹${t.sell_price.toFixed(2)}` : "—"}</td>
                  <td className="text-red">{t.stop_loss_price ? `₹${t.stop_loss_price.toFixed(2)}` : "—"}</td>
                  <td className="text-green">{t.target_price != null ? `₹${t.target_price.toFixed(2)}` : "—"}</td>
                  <td>{fmtDate(t.purchase_date)}</td>
                  <td>{fmtDate(t.sell_date)}</td>
                  <td className={(t.net_profit ?? 0) >= 0 ? "text-green" : "text-red"}>
                    {t.net_profit != null ? `₹${t.net_profit.toFixed(2)}` : "—"}
                  </td>
                  <td>{t.charges != null ? `₹${t.charges.toFixed(2)}` : "—"}</td>
                  <td>{t.tax != null ? `₹${t.tax.toFixed(2)}` : "—"}</td>
                  <td>{t.exit_reason ?? "—"}</td>
                  <td>
                    <span className={`pill ${t.status}`}>{t.status}</span>
                  </td>
                  <td>
                    {t.status === "open" && (
                      <button className="btn btn-close" disabled={closingId === t.trade_id} onClick={() => handleClose(t.trade_id)}>
                        {closingId === t.trade_id ? "Closing…" : "Close"}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
