from app.strategies.base import Strategy
from app.strategies.llm_recommendation import LlmRecommendationStrategy
from app.strategies.momentum_breakout import MomentumBreakoutStrategy
from app.strategies.watchlist_trigger import WatchlistTriggerStrategy

STRATEGY_REGISTRY: dict[str, type[Strategy]] = {
    "watchlist_trigger": WatchlistTriggerStrategy,
    "momentum_breakout": MomentumBreakoutStrategy,
    "llm_recommendation": LlmRecommendationStrategy,
    # Same scan() as llm_recommendation (it's universe/prompt-agnostic) -
    # registered separately so an agent can carry risk config and actually
    # trade on these signals while llm_recommendation itself stays
    # recommend-only. See agent_runtime.run_agent_scan / _find_recommend_only_agent.
    "llm_recommendation_execution": LlmRecommendationStrategy,
}


def get_strategy(name: str) -> Strategy:
    cls = STRATEGY_REGISTRY.get(name)
    if cls is None:
        raise ValueError(
            f"Unknown strategy '{name}'. Registered: {list(STRATEGY_REGISTRY)}"
        )
    return cls()
