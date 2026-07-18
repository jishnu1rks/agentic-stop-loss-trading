import { useCallback, useEffect, useState } from "react";
import { api, auth } from "./api/client";
import type { Kpis } from "./api/types";
import Sidebar, { type View } from "./components/Sidebar";
import LoginGate from "./components/LoginGate";
import DashboardPage from "./pages/DashboardPage";
import OpenTradesPage from "./pages/OpenTradesPage";
import HistoryPage from "./pages/HistoryPage";
import AgentSettingsPage from "./pages/AgentSettingsPage";

const TITLES: Record<View, string> = {
  dashboard: "Dashboard",
  "open-trades": "Open trades",
  history: "History",
  "agent-settings": "Agent settings",
};

type Theme = "dark" | "light";

function App() {
  const [view, setView] = useState<View>("dashboard");
  const [kpis, setKpis] = useState<Kpis | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshTick, setRefreshTick] = useState(0);
  const [theme, setTheme] = useState<Theme>(() => (localStorage.getItem("theme") as Theme) ?? "dark");
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("theme", theme);
  }, [theme]);

  const loadTopLevel = useCallback(() => {
    api
      .kpis()
      .then((k) => {
        setKpis(k);
        setError(null);
      })
      .catch(() => setError("Could not reach the backend API. Is it running on port 8000?"));
  }, []);

  useEffect(() => {
    loadTopLevel();
  }, [loadTopLevel, refreshTick]);

  const refreshAll = () => setRefreshTick((t) => t + 1);

  return (
    <LoginGate>
      <div className="app-shell">
        <Sidebar active={view} onChange={setView} mobileOpen={mobileNavOpen} onClose={() => setMobileNavOpen(false)} />

        <div className="main-content">
          <div className="app-header">
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <button
                className="hamburger-btn"
                onClick={() => setMobileNavOpen(true)}
                aria-label="Open navigation menu"
              >
                ☰
              </button>
              <div>
                <h1>{TITLES[view]}</h1>
                <div className="subtitle">Phase 1 simulation · paper trading against real/delayed market data</div>
              </div>
            </div>
            <div style={{ display: "flex", gap: 10 }}>
              <button
                className="refresh-btn"
                onClick={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
                aria-label="Toggle light/dark theme"
              >
                {theme === "dark" ? "☀ Light" : "🌙 Dark"}
              </button>
              <button className="refresh-btn" onClick={refreshAll}>
                Refresh
              </button>
              {auth.hasStoredCredentials() && (
                <button className="refresh-btn" onClick={() => { auth.logout(); window.location.reload(); }}>
                  Log out
                </button>
              )}
            </div>
          </div>

          {error && <div className="error-banner">{error}</div>}

          {view === "dashboard" && <DashboardPage kpis={kpis} onChanged={refreshAll} />}
          {view === "open-trades" && <OpenTradesPage refreshTick={refreshTick} onChanged={refreshAll} />}
          {view === "history" && <HistoryPage refreshTick={refreshTick} />}
          {view === "agent-settings" && <AgentSettingsPage refreshTick={refreshTick} onChanged={refreshAll} />}
        </div>
      </div>
    </LoginGate>
  );
}

export default App;
