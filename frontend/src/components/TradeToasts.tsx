import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { Trade } from "../api/types";

const POLL_INTERVAL_MS = 20 * 1000;
const TOAST_LIFETIME_MS = 6000;

// Exit reasons the monitor sets on its own, without direct user action - a
// manual close is tagged "manual" and skips the toast since the user just
// did it themselves and already has UI feedback for it.
const AUTO_EXIT_REASONS = new Set(["stop_loss", "target", "timeout"]);

type Toast = { id: string; text: string };

export default function TradeToasts() {
  const [toasts, setToasts] = useState<Toast[]>([]);
  // Previous poll's trades by id, so we diff for what's new/changed rather
  // than toasting on every fetch. null until the first poll completes -
  // that first poll only seeds the baseline, it never toasts (otherwise
  // every already-open trade would toast on page load).
  const seenRef = useRef<Map<string, Trade> | null>(null);

  useEffect(() => {
    const pushToast = (text: string) => {
      const id = `${Date.now()}-${Math.random()}`;
      setToasts((prev) => [...prev, { id, text }]);
      setTimeout(() => setToasts((prev) => prev.filter((t) => t.id !== id)), TOAST_LIFETIME_MS);
    };

    const poll = () => {
      api
        .listTrades()
        .then((trades) => {
          const prevSeen = seenRef.current;
          if (prevSeen) {
            for (const trade of trades) {
              const prev = prevSeen.get(trade.trade_id);
              if (!prev && trade.status === "open" && !trade.is_manual) {
                pushToast(`Agent bought ${trade.quantity} ${trade.stock_symbol} @ ${trade.buy_price}`);
              } else if (prev?.status === "open" && trade.status === "closed" && AUTO_EXIT_REASONS.has(trade.exit_reason ?? "")) {
                pushToast(`Agent exited ${trade.stock_symbol} (${trade.exit_reason}) @ ${trade.sell_price}`);
              }
            }
          }
          seenRef.current = new Map(trades.map((t) => [t.trade_id, t]));
        })
        .catch(() => {});
    };

    poll();
    const interval = setInterval(poll, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, []);

  if (toasts.length === 0) return null;

  return (
    <div className="toast-stack">
      {toasts.map((t) => (
        <div key={t.id} className="toast">
          {t.text}
        </div>
      ))}
    </div>
  );
}
