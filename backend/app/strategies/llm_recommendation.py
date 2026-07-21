"""
LLM-driven strategy (Section 5.3's pluggable seam): sends the universe's
current price/volume snapshot to an LLM along with the agent's configured
trading prompt, and parses back buy/sell signals. Anthropic and Gemini are
both wired in (settings.llm_provider picks which); structured outputs on
either provider guarantee valid JSON so a malformed model response can't
reach the entry pipeline. Any API failure is treated the same as a "no
signal" scan rather than raised, consistent with this system's fail-safe
posture (Section 9) for external-dependency errors.
"""
import json

import anthropic
from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types

from app.adapters.market_data.base import MarketDataSnapshot
from app.config import settings
from app.strategies.base import Signal, Strategy

_SIGNAL_SCHEMA = {
    "type": "object",
    "properties": {
        "signals": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "direction": {"type": "string", "enum": ["buy", "sell"]},
                    "confidence": {"type": "number"},
                    "reason": {"type": "string"},
                },
                "required": ["symbol", "direction", "confidence", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["signals"],
    "additionalProperties": False,
}

_SYSTEM_PREAMBLE = (
    "You are a trading signal generator embedded in an automated system. "
    "You will be given a trading strategy description and a snapshot of "
    "current market data. Return only symbols that CURRENTLY meet the "
    "strategy's entry criteria as of this snapshot - do not invent signals "
    "for symbols that don't qualify. Returning no signals at all is a "
    "normal, expected outcome."
)


def _build_market_summary(universe: list[str], snapshot: MarketDataSnapshot) -> str:
    lines = []
    for symbol in universe:
        price = snapshot.prices.get(symbol)
        if price is None:
            continue
        line = f"{symbol}: cmp={price:g}"
        history = snapshot.history.get(symbol)
        if history:
            line += f", {len(history)}d range={min(history):g}-{max(history):g}"
        volumes = snapshot.volumes.get(symbol)
        if volumes:
            line += f", latest volume={volumes[-1]:,.0f}"
        lines.append(line)
    return "\n".join(lines)


def _user_content(prompt: str, universe: list[str], market_summary: str) -> str:
    return (
        f"Strategy:\n{prompt}\n\n"
        f"Universe: {', '.join(universe)}\n\n"
        f"Current snapshot:\n{market_summary}"
    )


def _call_anthropic(user_content: str) -> str | None:
    """Returns the model's raw text reply, or None on an API-level failure."""
    try:
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        response = client.messages.create(
            model=settings.recommendation_model,
            max_tokens=2048,
            system=_SYSTEM_PREAMBLE,
            output_config={"format": {"type": "json_schema", "schema": _SIGNAL_SCHEMA}},
            messages=[{"role": "user", "content": user_content}],
        )
    except anthropic.APIError:
        return None
    return next((block.text for block in response.content if block.type == "text"), "")


def _call_gemini(user_content: str) -> str | None:
    """Returns the model's raw text reply, or None on an API-level failure."""
    try:
        client = genai.Client(api_key=settings.gemini_api_key)
        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=user_content,
            config=genai_types.GenerateContentConfig(
                system_instruction=_SYSTEM_PREAMBLE,
                response_mime_type="application/json",
                response_json_schema=_SIGNAL_SCHEMA,
            ),
        )
    except genai_errors.APIError:
        return None
    return response.text or ""


def _parse_signals(text: str, universe: list[str]) -> list[Signal]:
    try:
        data = json.loads(text) if text else {}
    except json.JSONDecodeError:
        return []

    universe_set = set(universe)
    signals = []
    for item in data.get("signals", []):
        symbol = item.get("symbol")
        direction = item.get("direction")
        if symbol not in universe_set or direction not in ("buy", "sell"):
            continue
        try:
            confidence = float(item.get("confidence", 0))
        except (TypeError, ValueError):
            confidence = 0.0
        signals.append(
            Signal(
                symbol=symbol,
                direction=direction,
                confidence=confidence,
                reason=str(item.get("reason", "")),
            )
        )
    return signals


class LlmRecommendationStrategy(Strategy):
    def scan(
        self,
        universe: list[str],
        market_data: MarketDataSnapshot,
        params: dict,
    ) -> list[Signal]:
        prompt = (params.get("prompt") or "").strip()
        if not prompt:
            return []

        provider = settings.llm_provider
        if provider == "gemini":
            if not settings.gemini_api_key:
                # Fail-safe: no key configured yet - treat exactly like a
                # paused scan rather than raising (Section 9).
                return []
        elif not settings.anthropic_api_key:
            return []

        market_summary = _build_market_summary(universe, market_data)
        if not market_summary:
            return []

        user_content = _user_content(prompt, universe, market_summary)
        text = _call_gemini(user_content) if provider == "gemini" else _call_anthropic(user_content)
        if text is None:
            # Fail-safe: an LLM outage pauses this scan cycle rather than
            # acting on no data, same posture as MarketDataUnavailableError.
            return []

        return _parse_signals(text, universe)
