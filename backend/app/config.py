"""
Central config. All values are env-driven (Section 9: credentials must never
live in the DB or dashboard) so switching phases/providers is a .env change,
not a code change.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")

    # Phase 1 default: SQLite, portable to Postgres later via DATABASE_URL.
    database_url: str = "sqlite:///./trading.db"

    # Adapter selection - interchangeable per Section 3.2.
    broker_provider: str = "simulator"        # simulator | kite
    market_data_provider: str = "yfinance"    # yfinance | kite

    # Kite Connect credentials (Phase 2). Never stored in DB.
    kite_api_key: str | None = None
    kite_api_secret: str | None = None
    kite_access_token: str | None = None

    # LLM-driven "recommendation" agents (llm_recommendation strategy) - the
    # per-agent trading prompt is configurable (Section 5.2), but the model
    # provider itself is an operator setting, not exposed in the agent config
    # UI. llm_provider picks which of the two credential pairs below is used.
    llm_provider: str = "anthropic"  # anthropic | gemini
    anthropic_api_key: str | None = None
    recommendation_model: str = "claude-opus-4-8"
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash"

    # Simulated fill behavior
    simulator_slippage_pct: float = 0.0

    # Total capital the user has committed to this account (Phase 1: a
    # single static pool shared by all agents + manual trades, not
    # per-agent). Enforced as a hard cap on new entries - see
    # agent_runtime.get_capital_summary().
    account_starting_capital: float = 100_000.0

    # Charges model (Section 6.3) - defaults approximate Zerodha's published
    # NSE equity charge structure. These are estimates for dashboard
    # purposes, not filing-ready figures (see Section 6.3 disclaimer).
    brokerage_pct: float = 0.0003          # 0.03%
    brokerage_cap: float = 20.0            # per executed leg
    stt_delivery_pct: float = 0.001        # 0.1% both legs (buy treated as delivery)
    stt_intraday_sell_pct: float = 0.00025  # 0.025% sell leg only (short/MIS)
    exchange_txn_pct: float = 0.0000297    # NSE
    sebi_charges_pct: float = 0.0000001    # ₹10 per crore
    stamp_duty_buy_delivery_pct: float = 0.00015
    stamp_duty_buy_intraday_pct: float = 0.00003
    gst_pct: float = 0.18                  # on (brokerage + exchange + SEBI)

    # Tax model (Section 6.3) - STCG estimate only.
    stcg_tax_pct: float = 0.20

    # Scheduler (Section 9: respect Kite rate limits when scaling agents)
    scheduler_max_concurrent_scans: int = 5

    # Production access control - a single shared login (Basic Auth), not
    # per-user accounts. Unset in local dev = auth disabled (see auth.py).
    basic_auth_username: str | None = None
    basic_auth_password: str | None = None

    # CORS - comma-separated list of allowed frontend origins. Defaults to
    # local Vite dev server; set to the deployed frontend's URL in prod.
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173,https://agentic-stop-loss-trading.vercel.app/"


settings = Settings()
