import axios from "axios";
import type {
  Agent,
  AgentBreakdown,
  AgentConfigIn,
  ChargesBreakdown,
  Kpis,
  ManualTradeInput,
  OpenPositionPnl,
  Quote,
  Recommendation,
  Trade,
} from "./types";

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";
const AUTH_STORAGE_KEY = "basic_auth_credentials";

const client = axios.create({ baseURL: BASE_URL });

// Single shared login (Basic Auth) - stored for the browser tab's session
// only, re-attached to every request via this header rather than relying
// on the native browser Basic Auth prompt, which behaves inconsistently
// across CORS origins (frontend and backend are typically on different
// domains once deployed).
function applyStoredCredentials() {
  const stored = sessionStorage.getItem(AUTH_STORAGE_KEY);
  if (stored) {
    client.defaults.headers.common["Authorization"] = `Basic ${stored}`;
  }
}
applyStoredCredentials();

export const auth = {
  hasStoredCredentials: () => sessionStorage.getItem(AUTH_STORAGE_KEY) !== null,

  // Local dev leaves BASIC_AUTH_USERNAME/PASSWORD unset, so require_auth()
  // on the backend is a no-op - probe with no credentials first so the
  // login screen never shows up unless the backend actually enforces it.
  isRequired: async (): Promise<boolean> => {
    try {
      await axios.get(`${BASE_URL}/agents`);
      return false;
    } catch (e) {
      return (e as { response?: { status?: number } })?.response?.status === 401;
    }
  },

  login: async (username: string, password: string): Promise<boolean> => {
    const encoded = btoa(`${username}:${password}`);
    try {
      await axios.get(`${BASE_URL}/agents`, { headers: { Authorization: `Basic ${encoded}` } });
    } catch {
      return false;
    }
    sessionStorage.setItem(AUTH_STORAGE_KEY, encoded);
    client.defaults.headers.common["Authorization"] = `Basic ${encoded}`;
    return true;
  },

  logout: () => {
    sessionStorage.removeItem(AUTH_STORAGE_KEY);
    delete client.defaults.headers.common["Authorization"];
  },
};

export const api = {
  listAgents: () => client.get<Agent[]>("/agents").then((r) => r.data),
  agentsBreakdown: () => client.get<AgentBreakdown[]>("/dashboard/agents-breakdown").then((r) => r.data),
  agentRecommendations: (agentId: string) =>
    client.get<Recommendation[]>(`/agents/${agentId}/recommendations`).then((r) => r.data),
  updateAgent: (agentId: string, payload: AgentConfigIn) =>
    client.put<Agent>(`/agents/${agentId}`, payload).then((r) => r.data),
  setAgentActive: (agentId: string, active: boolean) =>
    client.post<Agent>(`/agents/${agentId}/activate`, null, { params: { active } }).then((r) => r.data),

  listTrades: (params?: Record<string, string | boolean | undefined>) =>
    client.get<Trade[]>("/trades", { params }).then((r) => r.data),
  openPositionsPnl: () => client.get<Record<string, OpenPositionPnl>>("/trades/open/pnl").then((r) => r.data),
  placeManualTrade: (payload: ManualTradeInput) =>
    client.post<Trade>("/trades/manual", payload).then((r) => r.data),
  closeTrade: (tradeId: string) =>
    client.post<Trade>(`/trades/${tradeId}/close`).then((r) => r.data),
  editProtection: (tradeId: string, payload: { stop_loss_price: number; target_price: number | null }) =>
    client.patch<Trade>(`/trades/${tradeId}/protection`, payload).then((r) => r.data),
  getQuote: (symbol: string) => client.get<Quote>(`/trades/quote/${encodeURIComponent(symbol)}`).then((r) => r.data),
  getTradeCharges: (tradeId: string) =>
    client.get<ChargesBreakdown>(`/trades/${tradeId}/charges`).then((r) => r.data),

  kpis: () => client.get<Kpis>("/dashboard/kpis").then((r) => r.data),
};
