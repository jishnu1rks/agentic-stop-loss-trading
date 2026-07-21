import json
from dataclasses import dataclass

import anthropic
import httpx
import pytest
from google.genai import errors as genai_errors
from google.genai.models import Models

from app.adapters.market_data.base import MarketDataSnapshot
from app.config import settings
from app.strategies.llm_recommendation import LlmRecommendationStrategy


@pytest.fixture(autouse=True)
def fake_api_key(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "anthropic")
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-ant-test-key")


@dataclass
class _FakeTextBlock:
    text: str
    type: str = "text"


@dataclass
class _FakeResponse:
    content: list


@dataclass
class _FakeGeminiResponse:
    text: str


def test_no_signal_when_prompt_missing():
    strategy = LlmRecommendationStrategy()
    snapshot = MarketDataSnapshot(prices={"RELIANCE": 2420.0}, history={})
    assert strategy.scan(["RELIANCE"], snapshot, {}) == []


def test_no_signal_when_no_prices_available():
    strategy = LlmRecommendationStrategy()
    snapshot = MarketDataSnapshot(prices={}, history={})
    assert strategy.scan(["RELIANCE"], snapshot, {"prompt": "buy dips"}) == []


def test_no_signal_when_api_key_missing(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", None)
    strategy = LlmRecommendationStrategy()
    snapshot = MarketDataSnapshot(prices={"RELIANCE": 2420.0}, history={})
    assert strategy.scan(["RELIANCE"], snapshot, {"prompt": "buy dips"}) == []


def test_parses_signals_from_model_response(monkeypatch):
    fake_reply = json.dumps(
        {"signals": [{"symbol": "RELIANCE", "direction": "buy", "confidence": 0.8, "reason": "oversold bounce"}]}
    )

    def fake_create(self, **kwargs):
        return _FakeResponse(content=[_FakeTextBlock(text=fake_reply)])

    monkeypatch.setattr(anthropic.resources.Messages, "create", fake_create)

    strategy = LlmRecommendationStrategy()
    snapshot = MarketDataSnapshot(prices={"RELIANCE": 2420.0}, history={"RELIANCE": [2400, 2410, 2420]})

    signals = strategy.scan(["RELIANCE"], snapshot, {"prompt": "buy oversold blue chips"})

    assert len(signals) == 1
    assert signals[0].symbol == "RELIANCE"
    assert signals[0].direction == "buy"
    assert signals[0].confidence == pytest.approx(0.8)


def test_ignores_signals_for_symbols_outside_universe(monkeypatch):
    fake_reply = json.dumps(
        {"signals": [{"symbol": "TCS", "direction": "buy", "confidence": 0.5, "reason": "not in universe"}]}
    )

    def fake_create(self, **kwargs):
        return _FakeResponse(content=[_FakeTextBlock(text=fake_reply)])

    monkeypatch.setattr(anthropic.resources.Messages, "create", fake_create)

    strategy = LlmRecommendationStrategy()
    snapshot = MarketDataSnapshot(prices={"RELIANCE": 2420.0}, history={})

    assert strategy.scan(["RELIANCE"], snapshot, {"prompt": "buy oversold blue chips"}) == []


def test_returns_no_signals_on_api_error(monkeypatch):
    def fake_create(self, **kwargs):
        raise anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))

    monkeypatch.setattr(anthropic.resources.Messages, "create", fake_create)

    strategy = LlmRecommendationStrategy()
    snapshot = MarketDataSnapshot(prices={"RELIANCE": 2420.0}, history={})

    assert strategy.scan(["RELIANCE"], snapshot, {"prompt": "buy oversold blue chips"}) == []


def test_no_signal_when_gemini_api_key_missing(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "gemini")
    monkeypatch.setattr(settings, "gemini_api_key", None)

    strategy = LlmRecommendationStrategy()
    snapshot = MarketDataSnapshot(prices={"RELIANCE": 2420.0}, history={})

    assert strategy.scan(["RELIANCE"], snapshot, {"prompt": "buy dips"}) == []


def test_parses_signals_from_gemini_response(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "gemini")
    monkeypatch.setattr(settings, "gemini_api_key", "test-gemini-key")

    fake_reply = json.dumps(
        {"signals": [{"symbol": "RELIANCE", "direction": "buy", "confidence": 0.8, "reason": "oversold bounce"}]}
    )

    def fake_generate_content(self, **kwargs):
        return _FakeGeminiResponse(text=fake_reply)

    monkeypatch.setattr(Models, "generate_content", fake_generate_content)

    strategy = LlmRecommendationStrategy()
    snapshot = MarketDataSnapshot(prices={"RELIANCE": 2420.0}, history={"RELIANCE": [2400, 2410, 2420]})

    signals = strategy.scan(["RELIANCE"], snapshot, {"prompt": "buy oversold blue chips"})

    assert len(signals) == 1
    assert signals[0].symbol == "RELIANCE"
    assert signals[0].direction == "buy"
    assert signals[0].confidence == pytest.approx(0.8)


def test_returns_no_signals_on_gemini_api_error(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "gemini")
    monkeypatch.setattr(settings, "gemini_api_key", "test-gemini-key")

    def fake_generate_content(self, **kwargs):
        raise genai_errors.APIError(code=500, response_json={}, response=None)

    monkeypatch.setattr(Models, "generate_content", fake_generate_content)

    strategy = LlmRecommendationStrategy()
    snapshot = MarketDataSnapshot(prices={"RELIANCE": 2420.0}, history={})

    assert strategy.scan(["RELIANCE"], snapshot, {"prompt": "buy oversold blue chips"}) == []
